"""Offline contracts against the unmodified wheel and the shipped Python environment.

Executed by check_official_contract.py, not collected in the legacy pytest venv.
No pytest install, pip invocation or mutation of the runtime is needed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib.metadata
import io
import json
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class OfficialContracts(unittest.TestCase):
    def test_original_wheel_bytes_and_import_origin(self):
        import parsehub

        self.assertTrue(Path(parsehub.__file__).resolve().is_relative_to(PARSER / "python"))
        self.assertEqual(importlib.metadata.version("parsehub"), METADATA["version"])
        original = PARSER / METADATA["wheel"]["filename"]
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), METADATA["wheel"]["sha256"])
        with zipfile.ZipFile(original) as wheel:
            sources = [
                name for name in wheel.namelist() if name.startswith("parsehub/") and not name.endswith("/")
            ]
            self.assertGreater(len(sources), 24)
            for name in sources:
                self.assertEqual((PARSER / "python" / name).read_bytes(), wheel.read(name), name)
        self.assertFalse(any("upstream-ParseHub" in path for path in sys.path))

    def test_registered_platforms_match_client(self):
        from media_downloader.official_bridge import discover_capabilities
        from media_downloader.platforms import PLATFORMS

        capabilities = discover_capabilities()
        self.assertEqual({item.id for item in capabilities}, set(PLATFORMS))
        self.assertTrue(all(item.available for item in capabilities))

    def test_video_preview_normalizes_provider_units_and_hides_urls(self):
        from parsehub.types.media_ref import VideoRef
        from parsehub.types.platform import Platform
        from parsehub.types.result import ParseResult

        from media_downloader.official_bridge import preview_from_result

        result = ParseResult(
            title="video",
            platform=Platform.DOUYIN,
            media=VideoRef(url="https://example.com/video?token=secret", duration=86000),
        )
        preview = preview_from_result(result, source_identity="opaque-post")
        self.assertEqual(preview.media[0].duration_seconds, 86)
        self.assertNotIn("secret", json.dumps(preview.to_dict()))
        self.assertNotIn("example.com", json.dumps(preview.to_dict()))

    def test_gallery_preview_preserves_media_order(self):
        from parsehub.types.media_ref import ImageRef
        from parsehub.types.platform import Platform
        from parsehub.types.result import ParseResult

        from media_downloader.official_bridge import preview_from_result

        result = ParseResult(
            platform=Platform.XHS,
            media=[
                ImageRef(url="https://example.com/1", width=30, height=40),
                ImageRef(url="https://example.com/2", width=50, height=60),
            ],
        )
        preview = preview_from_result(result, source_identity="gallery")
        self.assertEqual(preview.media_count, 2)
        self.assertEqual([item.width for item in preview.media], [30, 50])

    def test_live_photo_preview_retains_capability(self):
        from parsehub.types.media_ref import LivePhotoRef
        from parsehub.types.platform import Platform
        from parsehub.types.result import ParseResult

        from media_downloader.official_bridge import preview_from_result

        result = ParseResult(
            platform=Platform.XHS,
            media=LivePhotoRef(url="https://example.com/photo", video_url="https://example.com/motion"),
        )
        preview = preview_from_result(result, source_identity="live")
        self.assertTrue(preview.capability.live_photos)
        self.assertEqual(preview.media[0].kind, "livephoto")

    def test_document_previews_use_current_sdk_models(self):
        from parsehub.types.platform import Platform
        from parsehub.types.result import ParseResult, RichTextParseResult

        from media_downloader.official_bridge import preview_from_result

        article = RichTextParseResult(title="article", markdown_content="# text")
        article.platform = Platform.ZHIHU
        text = ParseResult(title="text", content="body", platform=Platform.WEIBO)
        self.assertEqual(preview_from_result(article, source_identity="article").media[0].extension, "md")
        self.assertEqual(preview_from_result(text, source_identity="text").media[0].extension, "txt")

    def test_missing_channels_credentials_fail_before_provider_request(self):
        from media_downloader.errors import AppError
        from media_downloader.official_adapter import OfficialAdapter

        with self.assertRaises(AppError) as error:
            OfficialAdapter("https://weixin.qq.com/sph/example", official_runtime=True)
        self.assertEqual(error.exception.code, "AUTH_REQUIRED")

    def test_changed_resource_rejected_before_download(self):
        from parsehub.types.media_ref import ImageRef
        from parsehub.types.platform import Platform
        from parsehub.types.result import ParseResult

        from media_downloader.errors import AppError
        from media_downloader.official_adapter import OfficialAdapter

        result = ParseResult(platform=Platform.DOUYIN, media=ImageRef(url="https://example.com/image"))
        adapter = OfficialAdapter("https://www.douyin.com/video/123", official_runtime=True)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AppError) as error:
                asyncio.run(adapter.download(result, Path(directory), None, expected_resource_id="old"))
            self.assertEqual(error.exception.code, "RESOURCE_CHANGED")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_real_gallery_download_bytes_order_and_progress(self):
        from parsehub.types.media_ref import ImageRef
        from parsehub.types.platform import Platform
        from parsehub.types.result import ParseResult
        from PIL import Image

        payloads = []
        for color in ("red", "blue"):
            stream = io.BytesIO()
            Image.new("RGB", (2, 2), color).save(stream, format="JPEG")
            payloads.append(stream.getvalue())

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_HEAD(self):
                payload = payloads[int(self.path[1:])]
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()

            def do_GET(self):
                self.do_HEAD()
                self.wfile.write(payloads[int(self.path[1:])])

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        progress = []

        async def transfer(directory):
            async def callback(*args, **_):
                progress.append(args[:3])

            result = ParseResult(
                title="ordered album",
                platform=Platform.DOUYIN,
                media=[
                    ImageRef(url=f"http://127.0.0.1:{server.server_port}/{index}", width=2, height=2)
                    for index in range(2)
                ],
            )
            downloaded = await result.download(directory, callback=callback, connections=1, concurrency=1)
            self.assertEqual([Path(item.path).read_bytes() for item in downloaded.media], payloads)
            self.assertTrue(progress)

        try:
            with tempfile.TemporaryDirectory() as directory:
                asyncio.run(transfer(Path(directory)))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    profile = json.loads((bundle / "profile.json").read_bytes())
    paths = {kind: (bundle / relative).resolve() for kind, relative in profile["components"].items()}
    if not all(path.is_relative_to(bundle) for path in paths.values()):
        raise ValueError("Component path escaped bundle")
    if Path(sys.executable).resolve() != paths["python-runtime"] / "python.exe":
        raise ValueError("Run contracts using the bundled Python")
    PARSER = paths["parsehub"]
    METADATA = json.loads((PARSER / "component.json").read_bytes())
    sys.path[:0] = [str(paths["worker"] / "app"), str(PARSER / "python")]
    # Provider print output belongs to test diagnostics, never the JSON receipt.
    with contextlib.redirect_stdout(sys.stderr):
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(OfficialContracts)
        )
    report = {
        "passed": result.wasSuccessful(),
        "tests_run": result.testsRun,
        "parsehub": METADATA["version"],
        "python": sys.version.split()[0],
        "official_wheel_sha256": METADATA["wheel"]["sha256"],
        "sdk_origin": "unmodified-official-wheel",
        "external_platform_requests": False,
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
