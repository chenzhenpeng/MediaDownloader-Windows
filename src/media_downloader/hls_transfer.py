"""Recover finite, plain MPEG-TS HLS without changing the upstream SDK.

All network access stays in the guarded HTTP client. FFmpeg receives only a
locally concatenated transport stream, never a remote playlist or URL.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urljoin

import httpx

from .errors import AppError
from .network import RequestGuard


def segments(text, source):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    allowed = ("#EXT-X-VERSION:", "#EXT-X-TARGETDURATION:", "#EXT-X-MEDIA-SEQUENCE:")
    if not lines or lines[0] != "#EXTM3U" or lines[-1] != "#EXT-X-ENDLIST":
        raise AppError("HLS_UNSUPPORTED", "暂不支持该直播或分层播放列表。")
    urls, duration, pending = [], 0.0, False
    for line in lines[1:-1]:
        if line.startswith("#EXTINF:"):
            if pending:
                raise AppError("HLS_INVALID", "视频分段清单不完整。")
            try:
                value = float(line.split(":", 1)[1].split(",", 1)[0])
                if not math.isfinite(value) or not 0 < value <= 120:
                    raise ValueError
            except ValueError:
                raise AppError("HLS_INVALID", "视频分段时长无效。") from None
            duration += value
            pending = True
        elif line.startswith(allowed):
            continue
        elif line.startswith("#"):
            # Fail closed for keys, byte ranges, maps, alternate tracks and extensions.
            raise AppError("HLS_UNSUPPORTED", "暂不支持该视频分段格式或加密方式。")
        else:
            if not pending or len(urls) >= 4096:
                raise AppError("HLS_INVALID", "视频分段清单无效或过大。")
            urls.append(urljoin(source, line))
            pending = False
    if pending or not urls or duration > 12 * 3600:
        raise AppError("HLS_INVALID", "视频分段清单不完整或过大。")
    return urls, duration


async def local_tool(argv):
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 120)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise AppError("HLS_MERGE_FAILED", "视频分段合并失败，请重试。")
    return output


async def recover_playlist(path: Path, source: str, callback, *, proxy=None):
    with path.open("rb") as stream:
        header = stream.read(7)
    if header != b"#EXTM3U":
        return
    if path.stat().st_size > 2 * 1024 * 1024:
        raise AppError("HLS_INVALID", "视频分段清单过大。")
    urls, duration = segments(path.read_text(encoding="utf-8-sig"), source)
    tools = [shutil.which(name) for name in ("ffmpeg", "ffprobe")]
    if not all(tools):
        raise AppError("MEDIA_TOOL_MISSING", "下载分段视频需要 FFmpeg 和 ffprobe，请检查执行环境。")
    guard = RequestGuard()
    async with httpx.AsyncClient(
        proxy=proxy, follow_redirects=True, max_redirects=5, timeout=30,
        event_hooks={"request": [guard]},
    ) as client:
        # A unique task-owned directory is removed on failure and cancellation.
        with tempfile.TemporaryDirectory(prefix="hls-", dir=path.parent) as temporary:
            root = Path(temporary)
            transport, merged = root / "input.ts", root / "output.mp4"
            total = 0
            with transport.open("xb") as output:
                for index, url in enumerate(urls):
                    size = 0
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes(64 * 1024):
                            size += len(chunk)
                            total += len(chunk)
                            if size > 64 * 1024 * 1024 or total > 4 * 1024**3:
                                raise AppError("HLS_TOO_LARGE", "视频分段超过下载大小限制。")
                            output.write(chunk)
                    if not size:
                        raise AppError("HLS_INCOMPLETE", "视频分段为空，请重试。")
                    await callback(index + 1, len(urls), "count")
            await local_tool([
                tools[0], "-hide_banner", "-loglevel", "error", "-nostdin",
                "-protocol_whitelist", "file", "-f", "mpegts", "-i", str(transport),
                "-map", "0:v:0", "-map", "0:a?", "-c", "copy", "-movflags", "+faststart", str(merged),
            ])
            probe = json.loads(await local_tool([
                tools[1], "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                "-of", "json", str(merged),
            ]))
            actual = float(probe.get("format", {}).get("duration", 0))
            if (not math.isfinite(actual) or abs(actual - duration) > max(2, duration * 0.02)
                    or not any(s.get("codec_type") == "video" for s in probe.get("streams", []))):
                raise AppError("HLS_INCOMPLETE", "视频合并后的时长不完整，请重试。")
            os.replace(merged, path)
