"""Create a signed channel catalog from already signed immutable releases."""

import argparse
import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from media_downloader.component_catalog import verify_catalog
from media_downloader.update_contracts import load_trust, verify_manifest


def build(releases, key, trust, sequence, *, now=None):
    entries = []
    for raw, signature in releases:
        verify_manifest(raw, signature, trust)
        entries.append(
            {"manifest": base64.b64encode(raw).decode(), "signature": base64.b64encode(signature).decode()}
        )
    clock = now or datetime.now(UTC)
    key_id = next(
        (name for name, public in trust.keys.items() if public == key.public_key().public_bytes_raw()), None
    )
    if key_id is None:
        raise ValueError("Catalog signing key is not trusted")
    data = {
        "schema_version": 1,
        "kind": "component-catalog",
        "channel": trust.channel,
        "key_id": key_id,
        "sequence": sequence,
        "published_at": clock.isoformat(),
        "expires_at": (clock + timedelta(days=30)).isoformat(),
        "releases": entries,
    }
    raw = json.dumps(data, sort_keys=True, indent=2).encode()
    signature = key.sign(raw)
    verify_catalog(raw, signature, trust, now=clock)
    return raw, signature


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release_dirs", nargs="+", type=Path)
    parser.add_argument("--trust", type=Path, default=Path("packaging/update-trust.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    key = serialization.load_pem_private_key(os.environ["ENGINE_SIGNING_KEY_PEM"].encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Expected Ed25519 signing key")
    releases = [
        ((path / "release.json").read_bytes(), (path / "release.sig").read_bytes())
        for path in args.release_dirs
    ]
    trust = load_trust(args.trust)
    if args.previous:
        previous, _ = verify_catalog(
            (args.previous / "catalog.json").read_bytes(),
            (args.previous / "catalog.sig").read_bytes(),
            trust,
            installed=True,
        )
        if args.sequence <= previous["sequence"]:
            raise ValueError("Catalog sequence must increase before publication")
    raw, signature = build(releases, key, trust, args.sequence)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "catalog.json").write_bytes(raw)
    (args.output / "catalog.sig").write_bytes(signature)
    print(json.dumps({"sequence": args.sequence, "releases": len(releases)}))


if __name__ == "__main__":
    main()
