import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from parsehub.errors import DownloadError
from parsehub.parsers.parser.wxchannels import WXChannelsVideoParseResult
from parsehub.types import VideoRef
from parsehub.utils.downloader import SegmentDownloader
from parsehub.utils.media_info import MediaInfoReader


def test_small_channels_video_requests_complete_range_without_cookie(tmp_path, monkeypatch):
    payload = b"small-video-response"
    seen = []

    def handle(request):
        assert "cookie" not in request.headers
        if request.method == "HEAD":
            return httpx.Response(200, headers={"Content-Length": str(len(payload))})
        seen.append(request.headers.get("range"))
        if request.headers.get("range") != "bytes=0-":
            raise httpx.RemoteProtocolError("CDN rejects plain GET")
        return httpx.Response(
            206,
            headers={"Content-Range": f"bytes 0-{len(payload) - 1}/{len(payload)}"},
            stream=httpx.ByteStream(payload),
        )

    monkeypatch.setattr(
        SegmentDownloader, "_client", lambda self: httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    monkeypatch.setattr(
        MediaInfoReader, "read", lambda **kwargs: SimpleNamespace(width=10, height=20, duration=1)
    )
    result = WXChannelsVideoParseResult(title="test", video=VideoRef(url="https://finder.video.qq.com/test"))
    downloaded = asyncio.run(result.download(tmp_path))
    assert Path(downloaded.media.path).read_bytes() == payload
    assert seen == ["bytes=0-"]


@pytest.mark.parametrize("content_range", ["bytes 0-1/4", "bytes 1-3/4", "bytes 0-3/5"])
def test_single_download_rejects_incomplete_partial_representation(tmp_path, monkeypatch, content_range):
    def handle(request):
        if request.method == "HEAD":
            return httpx.Response(200, headers={"Content-Length": "4"})
        return httpx.Response(206, headers={"Content-Range": content_range}, stream=httpx.ByteStream(b"abcd"))

    monkeypatch.setattr(
        SegmentDownloader, "_client", lambda self: httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    destination = tmp_path / "video.mp4"
    with pytest.raises(DownloadError):
        asyncio.run(SegmentDownloader("https://finder.video.qq.com/test", destination, max_retries=0).run())
    assert not destination.exists()
