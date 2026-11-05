"""Compile the current-user preview installer from the verified native payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "0.2.0-preview.13"


def machine(path):
    with path.open("rb") as stream:
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        assert stream.read(4) == b"PE\0\0"
        return struct.unpack("<H", stream.read(2))[0]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", type=Path, default=ROOT / ".cache/installer-tools/InnoSetup7/ISCC.exe")
    parser.add_argument("--qa", action="store_true")
    args = parser.parse_args()
    toolchain = json.loads((ROOT / "packaging/windows/toolchain.json").read_text(encoding="utf-8"))
    if digest(args.compiler) != toolchain["iscc_sha256"]:
        raise RuntimeError("Compiler does not match the pinned toolchain")
    assert machine(args.compiler) == 0x8664
    payload = ROOT / "dist/native/MediaDownloader"
    output = ROOT / "dist/release"
    output.mkdir(parents=True, exist_ok=True)
    required = [
        "MediaDownloader.exe",
        "MediaDownloader.pri",
        "MainWindow.xbf",
        "App.xbf",
        "backend/MediaBackend.exe",
        "engine/media-engine.exe",
        "engine/engine.json",
    ]
    if not all((payload / name).is_file() for name in required):
        raise RuntimeError("Build the native payload first")
    engine = json.loads((payload / "engine/engine.json").read_text(encoding="utf-8"))
    files = sorted(path for path in payload.rglob("*") if path.is_file())
    if any(path.suffix in {".db", ".sqlite3", ".lock"} for path in files):
        raise RuntimeError("Unexpected user data in the distribution")
    inventory = [
        {"path": path.relative_to(payload).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}
        for path in files
    ]
    inventory_path = output / f"MediaDownloader-{RELEASE}{'-QA' if args.qa else ''}-payload.json"
    inventory_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    for name in ["ChineseSimplified.isl", "InstallInfo.txt"]:
        path = ROOT / "packaging/windows" / name
        if not path.read_bytes().startswith(b"\xef\xbb\xbf"):
            path.write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    command = [
        str(args.compiler.resolve()),
        "/Qp",
        f"/DPayloadDir={payload}",
        f"/DReleaseDir={output}",
        str(ROOT / "packaging/windows/MediaDownloader.iss"),
    ]
    if args.qa:
        command.insert(2, "/DQA=1")
    log = ROOT / f"build/installer-compile{'-qa' if args.qa else ''}.log"
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    installer = output / f"MediaDownloader-{RELEASE}-win-x64{'-QA' if args.qa else ''}-Setup.exe"
    assert machine(installer) == 0x8664, "The setup loader itself must be native x64"
    report = {
        "release": RELEASE,
        "client": "0.2.0.dev13",
        "setup_machine": "x64",
        "engine": engine["engine_version"],
        "installer": installer.name,
        "bytes": installer.stat().st_size,
        "sha256": digest(installer),
        "payload_files": len(files),
        "inventory_sha256": digest(inventory_path),
        "signed": False,
        "install_scope": "current-user",
        "user_data_preserved": True,
    }
    (output / f"{'qa-' if args.qa else ''}release.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    (output / f"{'QA-' if args.qa else ''}SHA256SUMS.txt").write_text(
        f"{report['sha256']}  {installer.name}\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
