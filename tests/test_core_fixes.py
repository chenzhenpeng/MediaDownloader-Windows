import asyncio
from pathlib import Path

import httpx
from parsehub.parsers.parser.bilibili import BiliYtParse
from parsehub.provider_api.bilibili import BiliAPI
from parsehub.types import ImageParseResult, ImageRef, VideoParseResult, VideoRef
from parsehub.utils.downloader import SegmentDownloader
from parsehub.utils.helpers import SecretCookie


class UnreadableBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        raise AssertionError("Range probe must not read ignored-Range response body")
        yield b""


def test_range_probe_does_not_buffer_ignored_range_response():
    async def check():
        async def handler(request):
            if request.method == "HEAD":
                return httpx.Response(200, headers={"Content-Length": "1000000000"})
            return httpx.Response(200, headers={"Content-Length": "1000000000"}, stream=UnreadableBody())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            probe = await SegmentDownloader("https://example.test/file")._probe(client)
            assert probe.total_size == 1000000000
            assert not probe.supports_range

    asyncio.run(check())


def test_multi_file_callback_keeps_task_context(monkeypatch, tmp_path):
    async def fake_download(url, path, **kwargs):
        Path(path).write_bytes(b"image")
        return str(path)

    monkeypatch.setattr("parsehub.types.result.download", fake_download)
    seen = []

    async def callback(current, total, unit, *, task_id):
        seen.append((current, total, unit, task_id))

    result = ImageParseResult(title="images", photo=[ImageRef(url="https://example.test/a", width=10)])
    asyncio.run(result.download(tmp_path, callback=callback, callback_kwargs={"task_id": "task-1"}))
    assert seen == [(1, 1, "count", "task-1")]


def test_cancelled_download_cleans_owned_output(monkeypatch, tmp_path):
    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr("parsehub.types.result.download", cancelled)
    result = VideoParseResult(title="cancelled", video=VideoRef(url="https://example.test/a"))
    try:
        asyncio.run(result.download(tmp_path))
    except asyncio.CancelledError:
        pass
    assert not list(tmp_path.iterdir())


def test_bilibili_video_cookie_reaches_playback_request():
    async def check():
        async def handler(request):
            assert "SESSDATA=dummy" in request.headers.get("cookie", "")
            return httpx.Response(200, json={"data": {}})

        async with BiliAPI(cookie={"SESSDATA": "dummy"}) as provider:
            provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            await provider.get_video_playurl("https://www.bilibili.com/video/BV1xx411c7mD", 1, "b3", "b4")

    asyncio.run(check())
    parser = BiliYtParse(cookie=SecretCookie({"SESSDATA": "dummy"}))
    assert "SESSDATA\tdummy" in parser.get_cookie_text()
