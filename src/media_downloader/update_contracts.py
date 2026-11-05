"""Signed release contracts. Never execute a candidate before verification."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.version import InvalidVersion, Version

from . import PROTOCOL, __version__


class UpdateError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def fail(code, message):
    raise UpdateError(code, message)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=pairs)


@dataclass(frozen=True)
class Trust:
    channel: str
    keys: dict[str, bytes]
    allowed_hosts: tuple[str, ...] = ()
    manifest_url: str = ""
    signature_url: str = ""
    local_feed: Path | None = None
    catalog_url: str = ""
    catalog_signature_url: str = ""

    @property
    def configured(self):
        return bool(
            self.keys
            and (
                self.local_feed
                or self.manifest_url
                and self.signature_url
                or self.catalog_url
                and self.catalog_signature_url
            )
        )

    def check_url(self, value):
        try:
            url = urlsplit(value)
            valid = (
                url.scheme == "https"
                and url.hostname in self.allowed_hosts
                and url.port in {None, 443}
                and not url.username
                and not url.password
                and not url.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            fail("UPDATE_SOURCE", "更新地址不在允许的 HTTPS 来源中。")


def load_trust(path: Path, *, allow_local=False) -> Trust:
    try:
        if path.stat().st_size > 65536:
            raise ValueError("Oversize trust file")
        data = strict_json(path.read_bytes())
        if not isinstance(data, dict) or not isinstance(data.get("keys"), dict):
            raise ValueError("Invalid trust structure")
        if data["schema_version"] != 1 or data["channel"] not in {"stable", "beta"}:
            raise ValueError("Invalid configuration")
        keys = {key: base64.b64decode(value, validate=True) for key, value in data["keys"].items()}
        if (
            len(keys) > 8
            or any(len(value) != 32 for value in keys.values())
            or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) for name in keys)
        ):
            raise ValueError("Invalid keys")
        local = data.get("development_directory")
        if local and not allow_local:
            raise ValueError("Local feeds require explicit developer configuration")
        trust = Trust(
            data["channel"],
            keys,
            tuple(data.get("allowed_hosts", [])),
            data.get("manifest_url") or "",
            data.get("signature_url") or "",
            (path.parent / local).resolve() if local else None,
            data.get("catalog_url") or "",
            data.get("catalog_signature_url") or "",
        )
        if trust.configured and not local:
            trust.check_url(trust.catalog_url or trust.manifest_url)
            trust.check_url(trust.catalog_signature_url or trust.signature_url)
        return trust
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise UpdateError("UPDATE_CONFIG", "更新源配置无效，当前内核仍可使用。") from exc


def verify_manifest(raw: bytes, signature: bytes, trust: Trust, *, installed=False, now=None):
    if len(raw) > 131072 or len(signature) != 64:
        fail("UPDATE_SIGNATURE", "更新清单签名无效。")
    verified_keys = []
    for key_id, key in trust.keys.items():
        try:
            Ed25519PublicKey.from_public_bytes(key).verify(signature, raw)
            verified_keys.append(key_id)
        except (InvalidSignature, ValueError):
            pass
    if not verified_keys:
        fail("UPDATE_SIGNATURE", "更新清单未通过受信任公钥验证。")
    try:
        data = strict_json(raw)
        if not isinstance(data, dict) or data["schema_version"] != 1:
            raise ValueError("Unknown schema")
        if data["key_id"] not in verified_keys or data["channel"] != trust.channel:
            raise ValueError("Key/channel mismatch")
        if data["target"] != "windows-x86_64" or data["protocol_version"] != PROTOCOL:
            fail("UPDATE_INCOMPATIBLE", "此内核需要其他架构或更新版本的客户端。")
        if data.get("component", "engine") not in {"engine", "parsehub"}:
            fail("UPDATE_INCOMPATIBLE", "客户端暂不支持此更新组件。")
        if data.get("component") == "parsehub" and not re.fullmatch(
            r"rt1-[0-9a-f]{24}", data.get("requires_runtime_id", "")
        ):
            raise ValueError("Missing parser runtime contract")
        if (
            not Version(data["app_min_version"])
            <= Version(__version__)
            < Version(data["app_max_version_exclusive"])
        ):
            fail("UPDATE_INCOMPATIBLE", "此内核与当前客户端版本不兼容。")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}", data["engine_version"]):
            raise ValueError("Invalid version")
        for key, length in (("sha256", 64), ("inventory_sha256", 64), ("upstream_sha", 40)):
            if not isinstance(data[key], str) or not re.fullmatch(
                r"[0-9a-f]{" + str(length) + "}", data[key]
            ):
                raise ValueError("Invalid hash")
        for key, low, high in (
            ("sequence", 1, 2**53),
            ("size_bytes", 1, 2 * 1024**3),
            ("unpacked_size_bytes", 1, 4 * 1024**3),
            ("file_count", 1, 20000),
        ):
            if type(data[key]) is not int or not low <= data[key] <= high:
                raise ValueError("Invalid size or sequence")
        if (
            not isinstance(data["notes"], list)
            or len(data["notes"]) > 20
            or any(not isinstance(note, str) or len(note) > 500 for note in data["notes"])
        ):
            raise ValueError("Invalid notes")
        published = datetime.fromisoformat(data["published_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        if published.utcoffset() is None or expires.utcoffset() is None or expires <= published:
            raise ValueError("Invalid dates")
        if not installed:
            clock = now or datetime.now(UTC)
            if published > clock or expires <= clock:
                fail("UPDATE_EXPIRED", "更新清单已过期或系统时钟不正确，请稍后检查。")
        if trust.local_feed:
            if data["artifact_url"] != "engine.zip":
                raise ValueError("Local artifact must be engine.zip")
        else:
            trust.check_url(data["artifact_url"])
        return data
    except (ValueError, TypeError, KeyError, AttributeError, InvalidVersion) as exc:
        raise UpdateError("UPDATE_MANIFEST", "更新清单格式无效，未更改当前内核。") from exc


def release_id(manifest):
    return manifest["engine_version"] + "-" + manifest["sha256"][:12]


def digest_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
