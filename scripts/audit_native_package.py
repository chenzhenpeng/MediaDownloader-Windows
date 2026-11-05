"""Audit built files and prevent removed dependencies returning in incremental builds."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from build_installer import RELEASE

ROOT = Path(__file__).resolve().parents[1]


def main():
    payload = ROOT / "dist/native/MediaDownloader"
    lock = json.loads((ROOT / "packaging/media-tools-lock.json").read_bytes())
    groups = defaultdict(int)
    files = [p for p in payload.rglob("*") if p.is_file()]
    engine = json.loads((payload / "engine/engine.json").read_bytes())
    official = engine.get("layout") == "official-embedded"
    for path in files:
        relative = path.relative_to(payload)
        group = relative.parts[0] if len(relative.parts) > 1 else "client"
        groups[group] += path.stat().st_size
        assert path.name.casefold() not in {
            "onnxruntime.dll",
            "directml.dll",
            "opengl32sw.dll",
            "qt6gui.dll",
            "qt6widgets.dll",
        }, f"Unused dependency returned: {relative}"
        if any(part.casefold() in {"numpy", "cv2"} for part in relative.parts):
            assert official and relative.parts[0] == "engine", relative
    tools = payload / "engine/tools"
    assert not (tools / "_internal").exists(), "Duplicated yt-dlp runtime returned"
    assert not list(tools.glob("*.dll")), "Old shared FFmpeg DLLs survived the clean build"
    expected_tools = {
        "ffmpeg.exe": lock["ffmpeg"]["ffmpeg_sha256"],
        "ffprobe.exe": lock["ffmpeg"]["ffprobe_sha256"],
    }
    if official:
        assert not (tools / "yt-dlp.exe").exists(), "Duplicate yt-dlp executable returned"
        assert (payload / "engine/Lib/site-packages/yt_dlp/__init__.py").is_file()
    else:
        expected_tools["yt-dlp.exe"] = lock["yt-dlp"]["sha256"]
    for name, expected in expected_tools.items():
        assert hashlib.file_digest((tools / name).open("rb"), "sha256").hexdigest() == expected
    installer = ROOT / f"dist/release/MediaDownloader-{RELEASE}-win-x64-Setup.exe"
    previous = ROOT / "dist/release/MediaDownloader-0.2.0-preview.6-win-x64.msi"
    report = {
        "passed": True,
        "uncompressed_bytes": sum(groups.values()),
        "groups_bytes": {k: v for k, v in groups.items() if v > 1024**2},
        "installer_bytes": installer.stat().st_size if installer.exists() else None,
        "previous_installer_bytes": previous.stat().st_size if previous.exists() else None,
        "largest_files": [
            {"path": str(p.relative_to(payload)), "bytes": p.stat().st_size}
            for p in sorted(files, key=lambda p: p.stat().st_size, reverse=True)[:15]
        ],
    }
    if installer.exists() and previous.exists():
        assert report["installer_bytes"] < report["previous_installer_bytes"], "No measured installer saving"
    compact_report = ROOT / "dist/release/release.json"
    if compact_report.exists():
        compact = json.loads(compact_report.read_bytes())
        if compact.get("release") == RELEASE:
            setup = ROOT / "dist/release" / compact["installer"]
            assert setup.stat().st_size == compact["bytes"]
            assert hashlib.file_digest(setup.open("rb"), "sha256").hexdigest() == compact["sha256"]
            qa = json.loads((ROOT / "dist/release/qa-release.json").read_bytes())
            assert compact["inventory_sha256"] == qa["inventory_sha256"]
            acceptance = json.loads((ROOT / "review/native/installer-acceptance.json").read_bytes())
            assert acceptance["release"] == compact["release"] and acceptance["installed_native_launch"]
            assert (
                acceptance["repair_preserves_data"]
                and acceptance["uninstall_preserves_unknown_file_and_data"]
            )
            report.update(
                compact_installer_bytes=compact["bytes"],
                compact_reduction_percent=round((1 - compact["bytes"] / previous.stat().st_size) * 100, 2)
                if previous.exists()
                else None,
                compact_sha256=compact["sha256"],
                same_payload_as_accepted_qa=True,
            )
    target = ROOT / f"review/native/package-audit-{RELEASE}.json"
    assert report["installer_bytes"] or report.get("compact_installer_bytes"), (
        "No completed installer to audit"
    )
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
