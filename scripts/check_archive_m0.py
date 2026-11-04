"""Validate the generated ZIP under a fresh Chinese path with no engine override."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
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
    stage = parser.parse_args().milestone
    metadata = json.loads((ROOT / "review" / f"{stage}-artifacts.json").read_text(encoding="utf-8"))
    archive = ROOT / metadata["artifact"]
    with archive.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == metadata["sha256"]
    extraction_root = ROOT / ".local" / stage
    extraction_root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="中文解压验收-", dir=extraction_root))
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(directory)
    env = dict(
        os.environ,
        PATH=str(Path(os.environ["SystemRoot"]) / "System32"),
        MEDIA_DOWNLOADER_DATA_DIR=str(directory / "app-data"),
    )
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    start = time.monotonic()
    screenshot = directory / "window.png"
    subprocess.run(
        [str(directory / "MediaDownloader/MediaDownloader.exe"), "--smoke-test", str(screenshot)],
        env=env,
        check=True,
        timeout=45,
        creationflags=0x08000000,
    )
    evidence = json.loads(screenshot.with_suffix(".json").read_text(encoding="utf-8"))
    report = {
        "scope": "fresh Chinese extraction path on development host; not clean VM",
        "archive_sha256": metadata["sha256"],
        "default_engine_resolved": True,
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "evidence": evidence,
    }
    assert evidence["ui_frozen"] and evidence["engine"]["frozen"]
    if stage == "localized":
        assert evidence["chinese_translation_loaded"]
    if stage in {"platforms", "kuaishou", "review", "localized"}:
        from media_downloader.platforms import PLATFORMS

        assert evidence["engine"]["platform_count"] == len(PLATFORMS)
        assert all(spec.name in evidence["supported_details"] for spec in PLATFORMS.values())
    (ROOT / "review" / f"{stage}-archive-check.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
