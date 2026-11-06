"""Authenticated component discovery, separate from repository Latest releases."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.version import InvalidVersion, Version

from .update_contracts import UpdateError, fail, strict_json, verify_manifest


def newer(manifest, engine):
    """Normal updates never use the explicit rollback path or compare unequal only."""
    if manifest.get("component") == "environment-plan":
        return any(newer(item, engine) for item in manifest["components"])
    if manifest.get("component") in {"worker", "python-runtime", "media-tools"}:
        current = engine.component_versions.get(manifest["component"], "0")
        return Version(manifest["engine_version"]) > Version(current)
    current = engine.version
    if manifest.get("component") == "parsehub":
        current = engine.parser_component_version or engine.version
    if manifest.get("component", "engine") == "engine":
        current = engine.runtime_version or engine.version
    try:
        if manifest.get("parsehub_version") and engine.parser_version:
            upstream = Version(manifest["parsehub_version"])
            installed_upstream = Version(engine.parser_version)
            if upstream < installed_upstream:
                return False
        if manifest.get("component", "engine") == "engine" and engine.component == "parsehub":
            baseline = manifest.get("parser_component_version", manifest["engine_version"])
            if Version(baseline) < Version(engine.parser_component_version or engine.version):
                return False
        return Version(manifest["engine_version"]) > Version(current)
    except InvalidVersion:
        # Invalid versions are not sortable update candidates.
        return False


def verify_catalog(raw, signature, trust, *, now=None, installed=False):
    if len(raw) > 2 * 1024**2 or len(signature) != 64:
        fail("UPDATE_CATALOG", "组件更新目录大小或签名无效。")
    keys = []
    for name, key in trust.keys.items():
        try:
            Ed25519PublicKey.from_public_bytes(key).verify(signature, raw)
            keys.append(name)
        except (InvalidSignature, ValueError):
            pass
    if not keys:
        fail("UPDATE_SIGNATURE", "组件更新目录未通过签名验证。")
    try:
        data = strict_json(raw)
        clock = now or datetime.now(UTC)
        published = datetime.fromisoformat(data["published_at"])
        expires = datetime.fromisoformat(data["expires_at"])
        if (
            data["schema_version"] != 1
            or data["kind"] != "component-catalog"
            or data["channel"] != trust.channel
            or data["key_id"] not in keys
            or type(data["sequence"]) is not int
            or not 0 < data["sequence"] < 2**53
            or published.utcoffset() is None
            or expires.utcoffset() is None
            or expires <= published
            or not installed
            and not published <= clock < expires
            or not isinstance(data["releases"], list)
            or len(data["releases"]) > 200
        ):
            raise ValueError("Invalid catalog")
        releases = []
        for entry in data["releases"]:
            body = base64.b64decode(entry["manifest"], validate=True)
            signed = base64.b64decode(entry["signature"], validate=True)
            try:
                manifest = verify_manifest(body, signed, trust, now=clock, installed=installed)
            except UpdateError as exc:
                if exc.code in {"UPDATE_INCOMPATIBLE", "UPDATE_EXPIRED"}:
                    continue
                raise
            releases.append((manifest, body, signed))
        return data, releases
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise UpdateError("UPDATE_CATALOG", "组件更新目录格式或有效期无效。") from exc


def choose(releases, engine, runtime_id, *, component="all"):
    candidates = [
        item
        for item in releases
        if (component == "all" or item[0].get("component", "engine") == component)
        and newer(item[0], engine)
        and (
            item[0].get("component", "engine") == "engine" or item[0].get("requires_runtime_id") == runtime_id
        )
    ]
    # Prefer small compatible parser repairs. A runtime update can be installed next.
    return max(
        candidates,
        key=lambda item: (
            item[0].get("component") == "parsehub",
            Version(item[0].get("parsehub_version", "0")),
            Version(item[0]["engine_version"]),
        ),
        default=None,
    )
