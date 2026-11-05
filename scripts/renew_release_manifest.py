"""Refresh signed discovery metadata without changing the immutable engine archive."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from media_downloader.update_contracts import load_trust, verify_manifest


def renew(raw, signature, trust, key, *, now=None):
    # An expired feed can be renewed, but its signature and full contract must pass.
    manifest = verify_manifest(raw, signature, trust, installed=True)
    public = key.public_key().public_bytes_raw()
    if trust.keys.get(manifest["key_id"]) != public:
        raise ValueError("Signing key does not match the trusted release key")
    clock = now or datetime.now(UTC)
    manifest.update(
        sequence=manifest["sequence"] + 1,
        published_at=clock.isoformat(),
        expires_at=(clock + timedelta(days=30)).isoformat(),
    )
    renewed = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    signed = key.sign(renewed)
    verify_manifest(renewed, signed, trust, now=clock)
    return renewed, signed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--trust", type=Path, default=Path("packaging/update-trust.json"))
    args = parser.parse_args()
    key = serialization.load_pem_private_key(os.environ["ENGINE_SIGNING_KEY_PEM"].encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Expected an Ed25519 signing key")
    raw, signature = renew(
        (args.directory / "release.json").read_bytes(),
        (args.directory / "release.sig").read_bytes(),
        load_trust(args.trust),
        key,
    )
    (args.directory / "release.json").write_bytes(raw)
    (args.directory / "release.sig").write_bytes(signature)
    value = json.loads(raw)
    print(json.dumps({"engine_version": value["engine_version"], "sequence": value["sequence"]}))


if __name__ == "__main__":
    main()
