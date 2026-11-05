"""Run with an isolated Python containing the original official wheel, never the app venv."""

import argparse
import asyncio
import faulthandler
import hashlib
import importlib.metadata
import inspect
import io
import json
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    faulthandler.dump_traceback_later(45, exit=True)
    args = argparse.ArgumentParser()
    args.add_argument("--wheel", type=Path, required=True)
    args.add_argument("--output", type=Path, required=True)
    options = args.parse_args()
    interpreter_directory = Path(sys.executable).resolve().parent
    runtime_base_inside = Path(sys.base_prefix).resolve().is_relative_to(interpreter_directory)
    original_search_paths = list(sys.path)
    import parsehub
    from parsehub import ParseHub
    from parsehub.parsers.base import BaseParser
    from parsehub.parsers.parser.bilibili import BiliVideoParseResult
    from parsehub.types.media_ref import ImageRef, LivePhotoRef, VideoRef
    from parsehub.types.platform import Platform
    from parsehub.types.result import ParseResult

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from media_downloader.errors import AppError
    from media_downloader.official_bridge import discover_capabilities, preview_from_result

    package = Path(parsehub.__file__).resolve().parent
    checked = 0
    with zipfile.ZipFile(options.wheel) as archive:
        for name in archive.namelist():
            if name.startswith("parsehub/") and not name.endswith("/"):
                assert (package.parent / name).read_bytes() == archive.read(name), name
                checked += 1

    hub = ParseHub()
    registry = BaseParser.get_registry()
    capabilities = discover_capabilities()
    sample = ParseResult(
        title="preview proof",
        platform=Platform.DOUYIN,
        media=ImageRef(url="https://example.invalid/private?token=secret", width=2, height=2),
    )
    preview = preview_from_result(sample, source_identity="public-post-123").to_dict()
    assert preview["platform"] == "douyin" and preview["media_count"] == 1
    assert "secret" not in json.dumps(preview) and "example.invalid" not in json.dumps(preview)
    sample.media.ext = "../exe"
    try:
        preview_from_result(sample, source_identity="public-post-123")
    except AppError:
        pass
    else:
        raise AssertionError("Unsafe extension was accepted")
    text = preview_from_result(
        ParseResult(title="article", content="body", platform=Platform.WEIXIN), source_identity="article-123"
    )
    assert text.media[0].extension == "txt"
    live = preview_from_result(
        ParseResult(
            title="live", platform=Platform.XHS, media=LivePhotoRef(url="https://example.invalid/a.jpg")
        ),
        source_identity="live-123",
    )
    assert live.capability.live_photos
    bili_result = BiliVideoParseResult(
        title="bili", video=VideoRef(url="https://example.invalid/a.mp4", width=1920, height=1080)
    )
    bili_result.platform = Platform.BILIBILI
    bili = preview_from_result(bili_result, source_identity="bili-123")
    assert bili.media[0].width is None and bili.media[0].height is None
    matches = {
        url: hub.get_parser(url) is not None
        for url in (
            "https://www.douyin.com/video/123",
            "https://www.bilibili.com/video/BV1234567890",
            "https://www.xiaohongshu.com/explore/123",
            "https://v.kuaishou.com/7eIz9IAa",
            "https://weixin.qq.com/sph/Ak1tHVI5Bd",
        )
    }
    from PIL import Image

    image_bytes = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(image_bytes, format="JPEG")
    payload = image_bytes.getvalue()

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

    options.output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    progress = []

    async def callback(current, total, unit, *_, **__):
        progress.append(unit)

    async def transfer():
        result = ParseResult(
            title="official-package-proof",
            media=ImageRef(url=f"http://127.0.0.1:{server.server_port}/image.jpg"),
        )
        downloaded = await result.download(options.output / "downloads", callback=callback, connections=1)
        files = list(downloaded.output_dir.rglob("*.jpg"))
        assert len(files) == 1 and files[0].read_bytes() == payload

    try:
        asyncio.run(transfer())
    finally:
        server.shutdown()
        server.server_close()
    report = {
        "python_version": sys.version.split()[0],
        "runtime_base_inside_environment": runtime_base_inside,
        "initial_search_paths": original_search_paths,
        "version": importlib.metadata.version("parsehub"),
        "package_origin": str(package),
        "wheel_sha256": hashlib.sha256(options.wheel.read_bytes()).hexdigest(),
        "unmodified_package_files": checked,
        "registered_parsers": len(registry),
        "dynamic_capabilities": len(capabilities),
        "client_preview_conversion": True,
        "unsafe_extension_rejected": True,
        "document_preview_conversion": True,
        "live_photo_capability": True,
        "unverified_bilibili_dimensions_hidden": True,
        "parser_classes": [parser.__name__ for parser in registry],
        "platform_matching": matches,
        "hub_constructor": str(inspect.signature(ParseHub)),
        "local_transfer_bytes_verified": True,
        "progress_callback_received": bool(progress),
        "live_platform_parsing_tested": False,
    }
    (options.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
