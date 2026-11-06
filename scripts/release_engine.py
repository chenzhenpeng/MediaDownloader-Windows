"""Create a complete signed engine feed. Never uploads or publishes anything."""

from __future__ import annotations

import argparse
import base64
import json
import os
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from packaging.version import Version

from media_downloader import PROTOCOL
from media_downloader.update_archive import inventory_bytes
from media_downloader.update_contracts import Trust, digest_file, verify_manifest


def package_release(
    engine_dir,
    output,
    key,
    *,
    sequence,
    artifact_url="engine.zip",
    channel="beta",
    key_id="local-test",
    minimum="0.1.0.dev1",
    maximum="0.3.0",
    notes=None,
):
    if (engine_dir / "component.json").is_file():
        component = json.loads((engine_dir / "component.json").read_bytes())
        if component["kind"] not in {"worker", "python-runtime", "media-tools"}:
            raise ValueError("Official ParseHub is not a custom signed release")
        from media_downloader import UPSTREAM_SHA

        metadata = {
            "protocol": PROTOCOL,
            "target": component["target"],
            "engine_version": component["version"],
            "component": component["kind"],
            "upstream_sha": os.environ.get("GITHUB_SHA", UPSTREAM_SHA),
            "patchset": "split-components",
        }
        minimum, maximum = "0.3.0.dev1", "0.4.0"
    else:
        metadata = json.loads((engine_dir / "engine.json").read_text(encoding="utf-8"))
    if metadata.get("component") == "parsehub" and Version(minimum) < Version("0.2.0.dev6"):
        minimum = "0.2.0.dev6"
    if metadata.get("adapter_abi") and Version(minimum) < Version("0.2.0.dev11"):
        minimum = "0.2.0.dev11"
    if metadata.get("layout") == "official-embedded":
        minimum = "0.2.0.dev14"
    if metadata["protocol"] != PROTOCOL or metadata["target"] != "windows-x86_64":
        raise ValueError("Engine descriptor is incompatible with this release builder")
    output.mkdir(parents=True, exist_ok=False)
    inventory, inventory_hash, entries = inventory_bytes(engine_dir)
    archive = output / "engine.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as bundle:
        for relative in entries:
            bundle.write(engine_dir / relative, relative)
        bundle.writestr("files.json", inventory)
    now = datetime.now(UTC)
    manifest = {
        "schema_version": 1,
        "channel": channel,
        "sequence": sequence,
        "published_at": now.isoformat(),
        "expires_at": (now + timedelta(days=30)).isoformat(),
        "engine_version": metadata["engine_version"],
        "upstream_sha": metadata["upstream_sha"],
        "patchset_version": metadata["patchset"],
        "app_min_version": minimum,
        "app_max_version_exclusive": maximum,
        "protocol_version": PROTOCOL,
        "target": "windows-x86_64",
        "artifact_url": artifact_url,
        "size_bytes": archive.stat().st_size,
        "sha256": digest_file(archive),
        "inventory_sha256": inventory_hash,
        "file_count": len(entries) + 1,
        "unpacked_size_bytes": sum(item["size"] for item in entries.values()) + len(inventory),
        "notes": notes or ["解析内核兼容更新"],
        "key_id": key_id,
    }
    if metadata.get("component") == "parsehub":
        manifest.update(
            component="parsehub",
            requires_runtime_id=metadata["requires_runtime_id"],
            parsehub_version=metadata["parsehub_version"],
            windows_revision=metadata["engine_version"],
        )
    elif metadata.get("component") in {"worker", "python-runtime", "media-tools"}:
        manifest["component"] = metadata["component"]
    elif metadata.get("runtime_id"):
        manifest["runtime_id"] = metadata["runtime_id"]
        manifest["parser_component_version"] = metadata.get(
            "parser_component_version", metadata["engine_version"]
        )
    if metadata.get("source_kind") == "pypi-wheel":
        manifest["source_kind"] = "pypi-wheel"
        manifest["parsehub_version"] = metadata["parsehub_version"]
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    signature = key.sign(raw)
    trust = Trust(
        channel,
        {key_id: key.public_key().public_bytes_raw()},
        (urlsplit(artifact_url).hostname,) if artifact_url != "engine.zip" else (),
        local_feed=output if artifact_url == "engine.zip" else None,
    )
    verify_manifest(raw, signature, trust)
    (output / "release.json").write_bytes(raw)
    (output / "release.sig").write_bytes(signature)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("engine_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--artifact-url", required=True)
    parser.add_argument("--channel", choices=["stable", "beta"], default="stable")
    args = parser.parse_args()
    pem = args.key_file.read_bytes() if args.key_file else os.environ["ENGINE_SIGNING_KEY_PEM"].encode()
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Expected an Ed25519 private key")
    manifest = package_release(
        args.engine_dir.resolve(),
        args.output.resolve(),
        key,
        sequence=args.sequence,
        artifact_url=args.artifact_url,
        channel=args.channel,
        key_id=args.key_id,
    )
    public = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    print(
        json.dumps(
            {
                "engine_version": manifest["engine_version"],
                "sequence": args.sequence,
                "sha256": manifest["sha256"],
                "public_key": public,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
