import asyncio
import errno
import sqlite3

import httpx
import pytest
from parsehub.errors import DownloadError
from parsehub.types import ImageParseResult, ImageRef
from parsehub.utils.downloader import SegmentDownloader

from media_downloader.errors import AppError
from media_downloader.storage import Store, download_stem


def test_long_title_budget_accounts_for_repeated_folder_and_filename(tmp_path):
    work = tmp_path / ("a" * 70)
    stem = download_stem("中文标题" * 100, work)
    assert len(str(work.resolve())) + 24 + len(stem) * 2 <= 240
    assert 8 <= len(stem) <= 70
    with pytest.raises(AppError) as error:
        download_stem("title", tmp_path / ("a" * 200))
    assert error.value.code == "PATH_TOO_LONG"


def test_m0_database_upgrades_without_losing_encrypted_source(tmp_path):
    path = tmp_path / "old.db"
    store = Store(path)
    task_id = store.create("https://www.douyin.com/video/123", str(tmp_path))
    encrypted = store.get(task_id)["source"]
    store.close()
    legacy = sqlite3.connect(path)
    legacy.execute("ALTER TABLE tasks DROP COLUMN error_code")
    legacy.execute("PRAGMA user_version=1")
    legacy.commit()
    legacy.close()
    upgraded = Store(path)
    try:
        assert upgraded.get(task_id)["source"] == encrypted
        assert upgraded.get(task_id)["error_code"] == ""
        upgraded.update(task_id, error_code="NETWORK_TIMEOUT")
        assert upgraded.db.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        upgraded.close()


def test_forbidden_range_part_does_not_restart_whole_download(monkeypatch, tmp_path):
    heads = []

    async def check():
        async def handler(request):
            if request.method == "HEAD":
                heads.append(request)
                return httpx.Response(200, headers={"Content-Length": "32"})
            if request.headers.get("range") == "bytes=0-0":
                return httpx.Response(206, headers={"Content-Range": "bytes 0-0/32"}, content=b"a")
            return httpx.Response(403)

        downloader = SegmentDownloader(
            "https://cdn.example/video.mp4",
            tmp_path / "video.mp4",
            min_split_size=8,
            connections=2,
            max_retries=3,
        )
        monkeypatch.setattr(
            downloader, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        with pytest.raises(DownloadError):
            await downloader.run()

    asyncio.run(check())
    assert len(heads) == 1
    assert not list(tmp_path.iterdir())


def test_disk_full_does_not_try_other_cdn_or_leave_partial_output(monkeypatch, tmp_path):
    calls = []

    async def full(url, *args, **kwargs):
        calls.append(url)
        raise OSError(errno.ENOSPC, "disk full")

    monkeypatch.setattr("parsehub.types.result.download", full)
    parsed = ImageParseResult(
        title="disk", photo=[ImageRef(url="https://cdn.example/a", backup_urls=["https://other.example/a"])]
    )
    with pytest.raises(DownloadError):
        asyncio.run(parsed.download(tmp_path))
    assert calls == ["https://cdn.example/a"]
    assert not list(tmp_path.iterdir())
