"""Run actual frozen-runtime probes against the unsigned reviewed parser candidate."""

import argparse
import json
from pathlib import Path

from media_downloader.engine import resolve_engine
from media_downloader.engine_health import probe_engine
from media_downloader.update_archive import extract_archive, inventory_bytes, verify_inventory
from media_downloader.update_contracts import digest_file, load_trust, verify_manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("component", type=Path)
    parser.add_argument("--runtime-feed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    trust = load_trust(Path("packaging/update-trust.json"))
    manifest = verify_manifest(
        (args.runtime_feed / "release.json").read_bytes(),
        (args.runtime_feed / "release.sig").read_bytes(),
        trust,
        installed=True,
    )
    archive = args.runtime_feed / "engine.zip"
    if digest_file(archive) != manifest["sha256"] or archive.stat().st_size != manifest["size_bytes"]:
        raise ValueError("Runtime archive differs from its signed manifest")
    args.output.mkdir(parents=True, exist_ok=False)
    runtime_path = args.output / "runtime"
    extract_archive(archive, runtime_path, manifest)
    runtime = resolve_engine(runtime_path)
    candidate = resolve_engine(args.component.resolve(), runtime=runtime)
    before = inventory_bytes(args.component)[1]
    probe_engine(candidate)
    if before != inventory_bytes(args.component)[1]:
        raise ValueError("Runtime probe modified the parser component")
    verify_inventory(runtime_path, manifest)
    report = {
        "passed": True,
        "runtime_version": runtime.version,
        "component_version": candidate.version,
        "runtime_id": runtime.runtime_id,
        "frozen_describe_and_download_self_test": True,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
