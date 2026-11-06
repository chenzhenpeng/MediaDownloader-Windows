"""Worker entry for an isolated embedded runtime using unmodified upstream wheels."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
import importlib.metadata
import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import PROTOCOL


def offline_test(output):
    from parsehub.types.media_ref import ImageRef
    from parsehub.types.result import ParseResult
    from PIL import Image

    from .official_bridge import preview_from_result

    output.mkdir(parents=True, exist_ok=False)
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(image, format="JPEG")
    payload, progress = image.getvalue(), []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()

        def do_GET(self):
            self.do_HEAD()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def transfer():
        from parsehub.types.platform import Platform

        result = ParseResult(
            title="compatibility probe",
            platform=Platform.DOUYIN,
            media=ImageRef(url=f"http://127.0.0.1:{server.server_port}/image.jpg"),
        )
        preview = preview_from_result(result, source_identity="offline-probe")
        if preview.platform != "douyin" or preview.media_count != 1:
            raise ValueError("Upstream preview contract changed")

        async def callback(*args, **_):
            progress.append(args[:3])

        downloaded = await result.download(output / "downloads", callback=callback, connections=1)
        files = list(downloaded.output_dir.rglob("*.jpg"))
        if len(files) != 1 or files[0].read_bytes() != payload or not progress:
            raise ValueError("Upstream transfer contract changed")

    try:
        asyncio.run(transfer())
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    for option in ("--runtime-dir", "--worker-dir", "--parser-dir", "--tools-dir"):
        parser.add_argument(option, type=Path, required=True)
    args = parser.parse_args()
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="strict")
    runtime = args.runtime_dir.resolve(strict=True)
    worker_root = args.worker_dir.resolve(strict=True)
    parser_root = args.parser_dir.resolve(strict=True)
    tools = args.tools_dir.resolve(strict=True)
    if Path(sys.executable).resolve().parent != runtime:
        raise ValueError("Unexpected Python runtime")
    if not Path(__file__).resolve().is_relative_to(worker_root / "app"):
        raise ValueError("Unexpected worker code origin")
    descriptor = json.loads((worker_root / "component.json").read_bytes())
    package = json.loads((parser_root / "component.json").read_bytes())
    version, upstream = descriptor["version"], package["wheel"]["sha256"]
    directory = parser_root / "python"
    expected = package["version"]
    sys.path.insert(0, str(directory))
    import parsehub

    if (
        not Path(parsehub.__file__).resolve().is_relative_to(directory)
        or importlib.metadata.version("parsehub") != expected
    ):
        raise ValueError("Official package identity mismatch")
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        if not (tools / name).is_file():
            raise ValueError("Media tool is missing")
    os.environ["PATH"] = str(tools) + os.pathsep + os.environ.get("PATH", "")
    # Describe/self-test also verify the complete service import closure.
    from . import worker
    from .engine_server import serve
    from .official_adapter import OfficialAdapter
    from .official_bridge import discover_capabilities

    report = {
        "protocol": PROTOCOL,
        "engine_version": version,
        "upstream_sha": upstream,
        "runtime_layout": "split-components",
        "frozen": False,
        "platform_count": len(discover_capabilities()),
        "capabilities": [item.to_dict() for item in discover_capabilities()],
    }
    if args.self_test:
        with contextlib.redirect_stdout(sys.stderr):
            offline_test(args.output)
        report["passed"] = True
    if args.describe or args.self_test:
        sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
        return 0
    if not args.serve:
        raise ValueError("Worker requires an explicit command")
    worker.ENGINE_VERSION, worker.UPSTREAM_SHA = version, upstream
    execute = functools.partial(
        worker.execute, adapter_factory=functools.partial(OfficialAdapter, official_runtime=True)
    )
    with contextlib.redirect_stdout(sys.stderr):
        asyncio.run(serve(execute=execute))
    return 0
