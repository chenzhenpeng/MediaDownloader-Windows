"""Renew authenticated discovery records, retaining immutable artifact hashes."""

import argparse
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization

if __package__:
    from .build_component_catalog import build
    from .renew_engine_feed import renew
else:
    from build_component_catalog import build
    from renew_engine_feed import renew

from media_downloader.component_catalog import verify_catalog
from media_downloader.update_contracts import load_trust


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    trust = load_trust(Path("packaging/update-trust.json"))
    body, signature = (
        (args.directory / "catalog.json").read_bytes(),
        (args.directory / "catalog.sig").read_bytes(),
    )
    data, releases = verify_catalog(body, signature, trust, installed=True)
    if len(releases) != len(data["releases"]):
        raise ValueError("This publisher cannot renew every catalog entry; upgrade publisher first")
    key = serialization.load_pem_private_key(os.environ["ENGINE_SIGNING_KEY_PEM"].encode(), password=None)
    entries = [renew(raw, signed, trust, key) for _, raw, signed in releases]
    body, signature = build(entries, key, trust, data["sequence"] + 1)
    (args.directory / "catalog.json").write_bytes(body)
    (args.directory / "catalog.sig").write_bytes(signature)
    print(json.dumps({"sequence": data["sequence"] + 1, "releases": len(entries)}))


if __name__ == "__main__":
    main()
