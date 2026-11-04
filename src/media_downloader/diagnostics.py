"""Explicit offline engine self-test; never reported as a live-platform test."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def tool_paths() -> dict[str, Path]:
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).parent / "tools"
        return {name: root / f"{name}.exe" for name in ("yt-dlp", "ffmpeg", "ffprobe")}
    import shutil

    return {name: Path(path) for name in ("ffmpeg", "ffprobe") if (path := shutil.which(name))}


def configure_tools():
    paths = tool_paths()
    if getattr(sys, "frozen", False):
        for name in ("yt-dlp", "ffmpeg", "ffprobe"):
            if not paths[name].is_file():
                raise FileNotFoundError(f"Bundled {name} is missing")
        os.environ["MEDIA_DOWNLOADER_YTDLP"] = str(paths["yt-dlp"])
        os.environ["PATH"] = str(paths["ffmpeg"].parent) + os.pathsep + os.environ.get("PATH", "")


def self_test(engine_version: str, output: Path | None = None) -> dict:
    from . import PROTOCOL, UPSTREAM_SHA

    started = time.monotonic()
    configure_tools()
    from parsehub.parsers.base.ytdlp import _yt_dlp_base_cmd
    from parsehub.types import ImageParseResult, ImageRef, VideoParseResult, VideoRef

    from .adapter import capabilities

    output = output or Path(tempfile.mkdtemp(prefix="media-engine-selftest-"))
    output.mkdir(parents=True, exist_ok=True)
    tools = tool_paths()
    versions = {}
    commands = {"yt-dlp": [*_yt_dlp_base_cmd(), "--version"]}
    commands.update({name: [str(path), "-version"] for name, path in tools.items() if name != "yt-dlp"})
    for name, argv in commands.items():
        completed = subprocess.run(argv, capture_output=True, timeout=30, creationflags=0x08000000)
        completed.check_returncode()
        versions[name] = completed.stdout.decode("utf-8", errors="replace").splitlines()[0]

    subprocess.run(
        [
            str(tools["ffmpeg"]),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=32x32:d=0.2",
            "-c:v",
            "mpeg4",
            "-y",
            str(output / "fixture.mp4"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
        creationflags=0x08000000,
    )
    from PIL import Image

    Image.new("RGB", (16, 16), "blue").save(output / "fixture.jpg")
    content = {
        "/video.mp4": (output / "fixture.mp4").read_bytes(),
        "/image.jpg": (output / "fixture.jpg").read_bytes(),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_HEAD(self):
            self.respond(False)

        def do_GET(self):
            self.respond(True)

        def respond(self, body):
            data = content.get(self.path)
            if data is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if body:
                self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def download_checks():
        base = f"http://127.0.0.1:{server.server_port}"
        video = VideoParseResult(title="中文视频", video=VideoRef(url=base + "/video.mp4"))
        images = ImageParseResult(
            title="中文图集", photo=[ImageRef(url=base + "/image.jpg") for _ in range(2)]
        )
        result_video = await video.download(output / "中文下载")
        result_images = await images.download(output / "中文下载")
        assert Path(result_video.media.path).read_bytes() == content["/video.mp4"]
        assert len(result_images.media) == 2
        for item in result_images.media:
            assert Path(item.path).read_bytes() == content["/image.jpg"]
        assert result_video.media.width == 32
        return {"video": str(result_video.output_dir), "images": str(result_images.output_dir)}

    try:
        files = asyncio.run(download_checks())
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    report = {
        "kind": "offline_engine_self_test",
        "passed": True,
        "protocol": PROTOCOL,
        "engine_version": engine_version,
        "upstream_sha": UPSTREAM_SHA,
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "parsehub": importlib.metadata.version("parsehub"),
        "platform_count": sum(item["available"] for item in capabilities()),
        "capabilities": capabilities(),
        "tools": versions,
        "media_sha256": {key: hashlib.sha256(value).hexdigest() for key, value in content.items()},
        "outputs": files,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    (output / "self-test.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
