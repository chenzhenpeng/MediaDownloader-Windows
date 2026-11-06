"""Validate an explicit local FFmpeg pair without modifying that directory."""

import hashlib
import os
import struct
import subprocess
from pathlib import Path

from .update_archive import no_reparse
from .update_contracts import digest_file


def inspect_local_tools(directory):
    root = Path(directory).resolve(strict=True)
    no_reparse(root)
    files, versions = {}, {}
    for name in ("ffmpeg", "ffprobe"):
        path = root / (name + ".exe")
        no_reparse(path)
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("媒体工具不是 Windows 可执行文件。")
            stream.seek(0x3C)
            offset = struct.unpack("<I", stream.read(4))[0]
            if offset > 1024**2:
                raise ValueError("媒体工具 PE 头无效。")
            stream.seek(offset)
            if stream.read(4) != b"PE\0\0" or stream.read(2) != b"\x64\x86":
                raise ValueError("请选择 x64 版本的 FFmpeg 和 ffprobe。")
        files[path.name] = digest_file(path)
        result = subprocess.run(
            [str(path), "-version"],
            capture_output=True,
            timeout=15,
            creationflags=0x08000000 if os.name == "nt" else 0,
            check=True,
        )
        line = result.stdout.decode("utf-8", errors="replace").splitlines()[0]
        if not line.startswith(name + " version ") or len(line) > 1024:
            raise ValueError("无法识别媒体工具版本。")
        versions[name] = {"version": line}
    # Check formats used by the application rather than relying on a version string.
    result = subprocess.run(
        [str(root / "ffmpeg.exe"), "-hide_banner", "-formats"],
        capture_output=True,
        timeout=15,
        check=True,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    formats = result.stdout.decode("utf-8", errors="replace")
    if "mpegts" not in formats or "mp4" not in formats:
        raise ValueError("该 FFmpeg 缺少 MPEG-TS 或 MP4 支持。")
    data = {
        "schema": 1,
        "kind": "media-tools",
        "version": "1.0.0",
        "target": "windows-x86_64",
        "files": files,
        "versions": versions,
        "external_directory": str(root),
    }
    import json

    identity = (
        "media-tools-local-" + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]
    )
    return identity, data
