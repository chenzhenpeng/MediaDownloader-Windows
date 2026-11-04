import pytest
from parsehub.provider_api.kuaishou import KuaishouParser, direct_video_url
from parsehub.types import VideoParseResult, VideoRef

from media_downloader.adapter import ParseHubAdapter
from media_downloader.errors import AppError
from media_downloader.media_validation import validate_media_payloads


def test_kuaishou_prefers_whole_video_to_manifest():
    parser = KuaishouParser("https://www.kuaishou.com/short-video/test")
    parser.page_type = "VIDEO"
    parser.client = {
        "VisionVideoSetRepresentation:1": {"url": "https://cdn.example/a.m3u8", "width": 1276, "height": 720},
        "VisionVideoAdaptationSet:1": {"duration": 282400},
        f"VisionVideoDetailPhoto:{parser.video_id}": {"photoUrl": "https://cdn.example/a.mp4"},
    }
    result = parser.get_real_video_url()
    assert result.url == "https://cdn.example/a.mp4" and result.d == 282400
    adapter = ParseHubAdapter("https://v.kuaishou.com/test")
    preview = adapter.preview(VideoParseResult(video=VideoRef(url=result.url, duration=result.d)))
    assert preview.media[0].duration_seconds == 282.4


def test_direct_url_supports_backups_without_taking_playlist_segment():
    assert (
        direct_video_url("https://cdn.example/a.m3u8", [{"url": "https://cdn.example/a.mp4"}])
        == "https://cdn.example/a.mp4"
    )
    assert direct_video_url("https://cdn.example/segment.ts") is None


@pytest.mark.parametrize(
    "payload,code",
    [
        (b"#EXTM3U\n#EXTINF:5\na.ts\n", "STREAM_NOT_DOWNLOADED"),
        (b"\xef\xbb\xbf#EXTM3U\n", "STREAM_NOT_DOWNLOADED"),
        (b'<?xml version="1.0"?><MPD></MPD>', "STREAM_NOT_DOWNLOADED"),
        (b"<!doctype html><html>error</html>", "INVALID_MEDIA_RESPONSE"),
    ],
)
def test_manifest_or_error_page_cannot_be_completed_as_mp4(tmp_path, payload, code):
    path = tmp_path / "video.mp4"
    path.write_bytes(payload)
    with pytest.raises(AppError) as error:
        validate_media_payloads([path])
    assert error.value.code == code


def test_documents_are_not_rejected_as_binary_media(tmp_path):
    path = tmp_path / "正文.md"
    path.write_text("#EXTM3U is an example", encoding="utf-8")
    validate_media_payloads([path])


def test_source_worker_handshake_uses_stdout():
    import json
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "media_downloader.worker", "--serve"],
        input=b'{"type":"shutdown"}\n',
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0
    event = json.loads(result.stdout.splitlines()[0])
    assert event["type"] == "worker_ready"
