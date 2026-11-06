import asyncio
import json
from pathlib import Path

import httpx
import pytest

from media_downloader import hls_transfer as hls
from media_downloader.errors import AppError

PLAYLIST = "#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:2,\na.ts\n#EXTINF:3,\nb.ts\n#EXT-X-ENDLIST\n"


@pytest.mark.parametrize("change", [
    lambda p: p.replace("#EXT-X-ENDLIST", ""),
    lambda p: p.replace("#EXT-X-VERSION:3", '#EXT-X-KEY:METHOD=AES-128,URI="key"'),
    lambda p: p.replace("#EXT-X-VERSION:3", "#EXT-X-BYTERANGE:50@0"),
    lambda p: p.replace("2,", "nan,"),
    lambda p: p.replace("a.ts\n", ""),
])
def test_unsupported_or_incomplete_playlist_fails_closed(change):
    with pytest.raises(AppError):
        hls.segments(change(PLAYLIST), "https://example.org/media/index")


def test_segment_order_and_duration():
    urls, duration = hls.segments(PLAYLIST, "https://example.org/media/index")
    assert urls == ["https://example.org/media/a.ts", "https://example.org/media/b.ts"]
    assert duration == 5


@pytest.mark.parametrize("mode", ["success", "missing_segment", "short_output", "cancel"])
def test_transfer_is_atomic_and_cleans_partial_files(tmp_path, monkeypatch, mode):
    target = tmp_path / "movie.mp4"
    target.write_text(PLAYLIST, encoding="utf-8")
    guarded, fetched, progress = [], [], []
    client_class = httpx.AsyncClient

    async def guard(request):
        guarded.append(str(request.url))

    def response(request):
        fetched.append(str(request.url))
        if request.url.host == "example.org" and request.url.path.endswith("a.ts"):
            return httpx.Response(302, headers={"location": "https://cdn.example.org/a.ts"})
        if mode == "missing_segment" and request.url.path.endswith("b.ts"):
            return httpx.Response(404)
        return httpx.Response(200, content=b"TS")

    monkeypatch.setattr(hls, "RequestGuard", lambda: guard)
    monkeypatch.setattr(hls.shutil, "which", lambda name: name)
    monkeypatch.setattr(hls.httpx, "AsyncClient", lambda **kw: client_class(
        **kw, transport=httpx.MockTransport(response)
    ))

    async def tool(argv):
        if argv[0] == "ffmpeg":
            assert "file" == argv[argv.index("-protocol_whitelist") + 1]
            assert Path(argv[argv.index("-i") + 1]).read_bytes() == b"TSTS"
            Path(argv[-1]).write_bytes(b"completed media")
            return b""
        return json.dumps({"format": {"duration": 1 if mode == "short_output" else 5},
                           "streams": [{"codec_type": "video"}]}).encode()

    async def callback(*args):
        progress.append(args)
        if mode == "cancel":
            raise asyncio.CancelledError

    monkeypatch.setattr(hls, "local_tool", tool)
    if mode == "success":
        asyncio.run(hls.recover_playlist(target, "https://example.org/index", callback))
        assert target.read_bytes() == b"completed media"
        assert progress[-1] == (2, 2, "count")
    else:
        expected = {"missing_segment": httpx.HTTPStatusError, "short_output": AppError,
                    "cancel": asyncio.CancelledError}[mode]
        with pytest.raises(expected):
            asyncio.run(hls.recover_playlist(target, "https://example.org/index", callback))
        assert target.read_text(encoding="utf-8") == PLAYLIST
    assert guarded == fetched  # Includes each redirected segment request.
    assert list(tmp_path.iterdir()) == [target]
