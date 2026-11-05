"""Verify and extract a published runtime for application-package builds."""

import argparse
from pathlib import Path

from media_downloader.engine import resolve_engine
from media_downloader.engine_health import probe_engine
from media_downloader.update_archive import extract_archive, verify_inventory
from media_downloader.update_contracts import digest_file, load_trust, verify_manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("feed", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = verify_manifest(
        (args.feed / "release.json").read_bytes(),
        (args.feed / "release.sig").read_bytes(),
        load_trust(Path("packaging/update-trust.json")),
        installed=True,
    )
    archive = args.feed / "engine.zip"
    if (
        manifest.get("component", "engine") != "engine"
        or archive.stat().st_size != manifest["size_bytes"]
        or digest_file(archive) != manifest["sha256"]
    ):
        raise ValueError("Expected an authenticated complete execution runtime")
    if args.output.exists():
        raise ValueError("Runtime output must not exist")
    extract_archive(archive, args.output, manifest)
    verify_inventory(args.output, manifest)
    probe_engine(resolve_engine(args.output))
    print("Verified runtime materialized and frozen probes passed")


if __name__ == "__main__":
    main()
