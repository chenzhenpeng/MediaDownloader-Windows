"""Assemble an installer bundle from three signed components and an original wheel."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from media_downloader.engine import resolve_engine
from media_downloader.engine_health import probe_engine
from media_downloader.official_packages import check_latest, download_wheel, extract_wheel
from media_downloader.update_archive import extract_archive, verify_inventory
from media_downloader.update_contracts import digest_file, load_trust, verify_manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("feeds", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Bundle must use a new output directory")
    trust = load_trust(Path("packaging/update-trust.json"))
    roots = {}
    for kind in ("worker", "python-runtime", "media-tools"):
        feed = args.feeds / kind
        manifest = verify_manifest(
            (feed / "release.json").read_bytes(), (feed / "release.sig").read_bytes(), trust, installed=True
        )
        archive = feed / "engine.zip"
        if (
            manifest["component"] != kind
            or archive.stat().st_size != manifest["size_bytes"]
            or digest_file(archive) != manifest["sha256"]
        ):
            raise ValueError("Invalid signed component")
        target = args.output / "c" / {"worker": "w", "python-runtime": "p", "media-tools": "t"}[kind]
        target.parent.mkdir(parents=True, exist_ok=True)
        extract_archive(archive, target, manifest)
        verify_inventory(target, manifest)
        roots[kind] = target
    contract = json.loads((roots["python-runtime"] / "component.json").read_bytes())["contract"]
    wheel = check_latest()
    package = args.output / "c/h"
    package.mkdir()
    archive = package / wheel.filename
    download_wheel(wheel, archive)
    extract_wheel(archive, wheel, contract, package / "python")
    (package / "component.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "kind": "parsehub",
                "version": wheel.version,
                "target": "windows-x86_64",
                "wheel": asdict(wheel),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    roots["parsehub"] = package
    (args.output / "profile.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "components": {
                    kind: path.relative_to(args.output).as_posix() for kind, path in roots.items()
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    engine = resolve_engine(args.output.resolve())
    probe_engine(engine)
    print(json.dumps({"passed": True, "components": engine.component_versions}, indent=2))


if __name__ == "__main__":
    main()
