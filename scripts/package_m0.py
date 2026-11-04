"""Create a local validation archive with the default relative engine layout."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--milestone",
        choices=[
            "m0",
            "m1",
            "m2",
            "m3",
            "m4",
            "ui",
            "naming",
            "polish",
            "platforms",
            "kuaishou",
            "review",
            "localized",
        ],
        default="m0",
    )
    args = parser.parse_args()
    archive = ROOT / "dist" / args.milestone / f"MediaDownloader-{args.milestone.upper()}.zip"
    size = 0
    count = 0
    with zipfile.ZipFile(
        archive.with_suffix(".zip.part"), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3
    ) as output:
        for directory, prefix in (
            (ROOT / "dist" / args.milestone / "MediaDownloader", "MediaDownloader"),
            (ROOT / "dist" / args.milestone / "media-engine", "MediaDownloader/engine"),
        ):
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    output.write(path, f"{prefix}/{path.relative_to(directory).as_posix()}")
                    size += path.stat().st_size
                    count += 1
        output.write(ROOT / "qa/m0/clean-machine.ps1", "clean-machine.ps1")
        output.write(ROOT / "qa/m0/README.md", "M0-README.md")
        output.writestr(
            "README.txt",
            (
                f"Media Downloader {args.milestone.upper()} local test build\n"
                "Extract the entire archive, then run MediaDownloader/MediaDownloader.exe.\n"
                "Keep the engine and _internal directories with the executable.\n"
                "This archive is unsigned and is not a public release installer.\n"
                "The optional clean-machine.ps1 script is for separate release acceptance.\n"
            ),
        )
    archive.with_suffix(".zip.part").replace(archive)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {
        "artifact": str(archive.relative_to(ROOT)),
        "sha256": digest,
        "files": count,
        "uncompressed_bytes": size,
        "zip_bytes": archive.stat().st_size,
        "signed": False,
        "purpose": f"{args.milestone.upper()} local validation, not public release",
    }
    (ROOT / "review" / f"{args.milestone}-artifacts.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
