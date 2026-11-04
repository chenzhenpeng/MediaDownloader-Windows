import asyncio
import errno
import importlib
import json
import subprocess
import sys

import httpx
import pytest
from parsehub.errors import DownloadError, FallbackAttempt, FallbackError, ParseError, ToolExecutionError
from parsehub.types import ImageParseResult, ImageRef, VideoParseResult, VideoRef

from media_downloader.adapter import ParseHubAdapter, capabilities, resource_identity
from media_downloader.contracts import platform_for_url, validate_command
from media_downloader.errors import AppError, classify_error
from media_downloader.network import RequestGuard
from media_downloader.progress import ProgressReporter
from media_downloader.storage import extract_links


def test_explicit_parser_load_does_not_import_other_platform_sdks():
    code = """
import sys
class BlockOptionalPlatforms:
    def find_spec(self, name, path=None, target=None):
        if name in {'SignerPy','xhshow'}:
            raise ModuleNotFoundError('intentional optional dependency failure')
sys.meta_path.insert(0, BlockOptionalPlatforms())
from media_downloader.adapter import ParseHubAdapter
adapter = ParseHubAdapter('https://www.bilibili.com/video/BV123')
assert len(adapter.hub.parsers) == 1
assert 'parsehub.parsers.parser.douyin' not in sys.modules
assert 'parsehub.parsers.parser.instagram' not in sys.modules
assert 'parsehub.parsers.parser.xhs' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, timeout=20)


def test_one_platform_import_failure_does_not_disable_others(monkeypatch):
    original = importlib.import_module

    def unavailable(name, *args, **kwargs):
        if name == "parsehub.parsers.parser.douyin":
            raise ModuleNotFoundError("optional SDK missing")
        return original(name, *args, **kwargs)

    monkeypatch.setattr("media_downloader.adapter.importlib.import_module", unavailable)
    available = {item["id"]: item for item in capabilities()}
    assert not available["douyin"]["available"]
    assert available["bilibili"]["available"] and available["xhs"]["available"]


@pytest.mark.parametrize(
    "url",
    [
        "https://douyin.com.evil.test/video/1",
        "https://evil-douyin.com/a",
        "https://www.douyin.com@127.0.0.1/a",
        "file:///video.mp4",
        "https://www.douyin.com:1234/a",
        "https://[broken/a",
    ],
)
def test_entry_host_boundary_rejects_lookalikes_and_malformed_addresses(url):
    assert platform_for_url(url) is None
    assert extract_links(url) == []


def test_preview_contract_has_no_cdn_or_cookie_and_normalizes_duration():
    adapter = ParseHubAdapter("https://www.douyin.com/video/123")
    parsed = VideoParseResult(
        title="作品", video=VideoRef(url="https://cdn.example/a?token=private", duration=92900)
    )
    parsed.raw_url = "https://www.douyin.com/video/123?cookie=do-not-export"
    preview = adapter.preview(parsed).to_dict()
    assert preview["media"][0]["duration_seconds"] == 92.9
    assert preview["capability"]["format_selection"] is False
    assert len(preview["resource_id"]) == 64
    assert "private" not in json.dumps(preview) and "do-not-export" not in json.dumps(preview)


@pytest.mark.parametrize("duration", [None, float("inf"), float("nan")])
def test_missing_or_invalid_duration_remains_unknown_in_protocol(duration):
    adapter = ParseHubAdapter("https://www.douyin.com/video/123")
    parsed = VideoParseResult(video=VideoRef(url="https://cdn.example/a", duration=duration))
    preview = adapter.preview(parsed).to_dict()
    assert preview["media"][0]["duration_seconds"] is None
    json.dumps(preview, allow_nan=False)


def test_changed_resource_is_not_silently_downloaded(tmp_path):
    adapter = ParseHubAdapter("https://www.douyin.com/video/123")
    result = VideoParseResult(video="https://cdn.example/a.mp4")

    async def progress(*args):
        raise AssertionError("download must not start")

    with pytest.raises(AppError) as error:
        asyncio.run(adapter.download(result, tmp_path, progress, expected_resource_id="different"))
    assert error.value.code == "RESOURCE_CHANGED"
    assert not list(tmp_path.iterdir())


def test_same_resource_redirect_variants_do_not_require_reconfirmation():
    first = VideoParseResult(video="https://cdn.example/a")
    second = VideoParseResult(video="https://other-cdn.example/a")
    first.raw_url = "https://www.iesdouyin.com/share/video/123/?tracking=a"
    second.raw_url = "https://www.douyin.com/video/123"
    assert resource_identity("douyin", first, "") == resource_identity("douyin", second, "")
    first.raw_url = "https://www.bilibili.com/video/BV123?p=2"
    second.raw_url = "https://www.bilibili.com/video/BV123?p=1"
    assert resource_identity("bilibili", first, "") != resource_identity("bilibili", second, "")


def test_unavailable_format_and_unsafe_extension_are_rejected(tmp_path):
    adapter = ParseHubAdapter("https://www.douyin.com/video/123")
    result = VideoParseResult(video="https://cdn.example/a.mp4")
    with pytest.raises(AppError) as error:
        asyncio.run(adapter.download(result, tmp_path, None, selection="4k"))
    assert error.value.code == "FORMAT_UNAVAILABLE"
    with pytest.raises(AppError) as error:
        adapter.preview(ImageParseResult(photo=[ImageRef(url="https://cdn.example/a", ext="../../bad")]))
    assert error.value.code == "UNSUPPORTED_FORMAT"


def test_percent_and_count_never_masquerade_as_bytes():
    clock = [0.0]
    reporter = ProgressReporter("percent", clock=lambda: clock[0])
    clock[0] = 2.0
    progress = reporter.update(50, 100)
    assert progress["percent"] == 50
    assert progress["completed_bytes"] is None and progress["speed_bps"] is None
    items = ProgressReporter("count").update(2, 8)
    assert items["completed_items"] == 2 and items["total_items"] == 8
    assert items["total_bytes"] is None and items["speed_bps"] is None


def test_unknown_total_and_byte_retry_have_valid_progress():
    clock = [0.0]
    reporter = ProgressReporter("bytes", clock=lambda: clock[0])
    clock[0] = 2.0
    unknown = reporter.update(1000, 0)
    assert unknown["percent"] is None and unknown["total_bytes"] is None
    assert unknown["speed_bps"] == 500
    clock[0] = 3.0
    restarted = reporter.update(100, 1000)
    assert restarted["speed_bps"] is None


@pytest.mark.parametrize(
    "exc,phase,code",
    [
        (OSError(errno.ENOSPC, "secret path"), "downloading", "DISK_FULL"),
        (PermissionError(errno.EACCES, "secret path"), "finalizing", "PERMISSION_DENIED"),
        (DownloadError("secret signed URL", status_code=429), "downloading", "RATE_LIMITED"),
        (DownloadError("secret Cookie", status_code=401), "parsing", "AUTH_EXPIRED"),
        (httpx.ReadTimeout("proxy password secret"), "parsing", "NETWORK_TIMEOUT"),
        (ToolExecutionError("secret yt-dlp tail"), "downloading", "TOOL_FAILED"),
        (ParseError("需要登录后查看 secret"), "parsing", "AUTH_REQUIRED"),
    ],
)
def test_actionable_errors_do_not_leak_upstream_details(exc, phase, code):
    wrapped = FallbackError([FallbackAttempt("provider", exc)])
    result = classify_error(wrapped, phase).to_dict()
    assert result["code"] == code
    assert "secret" not in json.dumps(result)
    assert result["action"] and result["phase"] == phase


def test_fallback_retains_disk_error_under_download_wrapper():
    error = DownloadError("generic failure")
    error.__cause__ = OSError(errno.ENOSPC, "secret disk path")
    assert classify_error(error, "downloading").code == "DISK_FULL"


def test_request_guard_stops_private_dns_and_cross_platform_redirect(monkeypatch):
    async def private_addresses(host, port):
        return {"127.0.0.1"}

    monkeypatch.setattr("media_downloader.network.resolve_addresses", private_addresses)
    with pytest.raises(AppError) as error:
        asyncio.run(RequestGuard()(httpx.Request("GET", "https://cdn.example/a")))
    assert error.value.code == "UNSAFE_URL"
    with pytest.raises(AppError) as error:
        asyncio.run(RequestGuard("douyin")(httpx.Request("GET", "https://www.xiaohongshu.com/a")))
    assert error.value.code == "UNSAFE_REDIRECT"


def test_fake_ip_proxy_mapping_keeps_public_names_working_without_allowing_local_literals(monkeypatch):
    async def fake_ip_addresses(host, port):
        return {"198.18.0.206"} if host != "www.microsoft.com" else {"198.18.1.100"}

    monkeypatch.setattr("media_downloader.network.resolve_addresses", fake_ip_addresses)
    guard = RequestGuard("douyin")
    asyncio.run(guard(httpx.Request("GET", "https://v.douyin.com/a")))
    assert guard.fake_ip_mapping is True
    for url in ("http://198.18.0.206/a", "http://127.0.0.1/a", "http://10.1.1.1/a", "http://example.local/a"):
        with pytest.raises(AppError):
            asyncio.run(RequestGuard()(httpx.Request("GET", url)))


def test_benchmark_dns_is_not_allowed_without_independent_proxy_mapping(monkeypatch):
    async def isolated_mapping(host, port):
        return {"8.8.8.8"} if host == "www.microsoft.com" else {"198.18.0.1"}

    monkeypatch.setattr("media_downloader.network.resolve_addresses", isolated_mapping)
    with pytest.raises(AppError):
        asyncio.run(RequestGuard()(httpx.Request("GET", "https://cdn.example/a")))


def test_redirect_guard_runs_before_every_http_hop(monkeypatch):
    from parsehub.parsers.parser.douyin import DouyinParser

    async def public_addresses(host, port):
        return {"8.8.8.8"}

    monkeypatch.setattr("media_downloader.network.resolve_addresses", public_addresses)
    requests = []

    async def handler(request):
        requests.append(request.url.host)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    client = httpx.AsyncClient
    monkeypatch.setattr(
        "parsehub.parsers.base.base.httpx.AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )

    class Guarded(DouyinParser, register=False):
        request_guard = RequestGuard("douyin")

    with pytest.raises(ParseError) as error:
        asyncio.run(Guarded().get_raw_url("https://v.douyin.com/abc"))
    assert classify_error(error.value).code == "UNSAFE_REDIRECT"
    assert requests == ["v.douyin.com"]


@pytest.mark.parametrize(
    "bad", [[], {"action": []}, {"protocol": 1, "action": "inspect", "task_id": "../escape"}]
)
def test_invalid_commands_do_not_reach_filesystem(bad):
    with pytest.raises(AppError) as error:
        validate_command(bad, 1)
    assert error.value.code == "INVALID_COMMAND"
