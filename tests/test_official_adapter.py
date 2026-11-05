import asyncio
from types import SimpleNamespace

import pytest

from media_downloader.errors import AppError
from media_downloader.official_adapter import OfficialAdapter


def test_official_capabilities_are_usable_by_native_ui():
    from media_downloader import PROTOCOL
    from media_downloader.official_bridge import discover_capabilities
    from media_downloader.ui_capabilities import capability_copy

    capabilities = discover_capabilities()
    rows = capability_copy(
        {
            "protocol": PROTOCOL,
            "engine_version": "test",
            "capabilities": [item.to_dict() for item in capabilities],
        },
        "test",
    )
    assert len(rows) == 24
    assert any(name == "哔哩哔哩" and "视频" in types for name, types in rows)


def hub_for(monkeypatch, platform="douyin"):
    class Hub:
        def get_parser(self, _):
            return SimpleNamespace(__platform__=SimpleNamespace(id=platform))

    monkeypatch.setattr("parsehub.ParseHub", Hub)
    return Hub


def test_official_adapter_requires_explicit_opt_in():
    with pytest.raises(AppError) as error:
        OfficialAdapter("https://v.douyin.com/example")
    assert error.value.code == "OFFICIAL_NOT_ENABLED"


def test_video_channels_reports_credentials_before_provider_call(monkeypatch):
    hub_for(monkeypatch, "weixin_channels")
    with pytest.raises(AppError) as error:
        OfficialAdapter("https://weixin.qq.com/sph/example", experimental=True)
    assert error.value.code == "AUTH_REQUIRED" and error.value.action == "update_cookie"


def test_changed_resource_does_not_start_download(monkeypatch, tmp_path):
    hub_for(monkeypatch)
    monkeypatch.setattr(
        "media_downloader.official_adapter.preview_from_result",
        lambda *_, **__: SimpleNamespace(resource_id="different"),
    )
    adapter = OfficialAdapter("https://v.douyin.com/example", experimental=True)
    result = SimpleNamespace(raw_url="https://www.douyin.com/video/123")
    with pytest.raises(AppError) as error:
        asyncio.run(adapter.download(result, tmp_path, None, expected_resource_id="confirmed"))
    assert error.value.code == "RESOURCE_CHANGED"
    assert list(tmp_path.iterdir()) == []


def test_private_media_address_is_blocked_before_download(monkeypatch, tmp_path):
    hub_for(monkeypatch)
    monkeypatch.setattr(
        "media_downloader.official_adapter.preview_from_result",
        lambda *_, **__: SimpleNamespace(resource_id="same"),
    )
    adapter = OfficialAdapter("https://v.douyin.com/example", experimental=True)
    result = SimpleNamespace(
        raw_url="https://www.douyin.com/video/123",
        media=SimpleNamespace(url="http://127.0.0.1/private", backup_urls=[]),
    )
    with pytest.raises(AppError) as error:
        asyncio.run(adapter.download(result, tmp_path, None))
    assert error.value.code == "UNSAFE_URL"


def test_task_cancellation_propagates_to_upstream(monkeypatch, tmp_path):
    hub_for(monkeypatch)
    monkeypatch.setattr(
        "media_downloader.official_adapter.preview_from_result",
        lambda *_, **__: SimpleNamespace(resource_id="same"),
    )
    adapter = OfficialAdapter("https://v.douyin.com/example", experimental=True)

    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def download(*_, **__):
            entered.set()
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()

        result = SimpleNamespace(raw_url="https://www.douyin.com/video/123", media=None, download=download)
        task = asyncio.create_task(adapter.download(result, tmp_path, None))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()

    asyncio.run(scenario())
