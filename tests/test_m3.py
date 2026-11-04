import asyncio
import base64
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
from parsehub.types import ImageParseResult, ImageRef
from PIL import Image
from test_m2_tasks import local_engine as local_engine
from test_worker_integration import wait_for

from media_downloader.artwork import fetch_artwork, normalize_image
from media_downloader.engine import resolve_engine
from media_downloader.presentation import diagnostic_report, progress_text
from media_downloader.storage import Store
from media_downloader.task_files import create_work_directory


def test_artwork_is_bounded_normalized_and_contains_no_remote_url(monkeypatch):
    image = io.BytesIO()
    Image.new("RGB", (1024, 768), "navy").save(image, "PNG")
    calls = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield image.getvalue()

    async def handle(request):
        calls.append(request)
        return httpx.Response(200, headers={"Content-Type": "image/png"}, stream=Stream())

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handle))
    )

    async def guard(request):
        assert request.url.host == "cdn.example"

    result = ImageParseResult(photo=[ImageRef(url="https://cdn.example/image?secret=hidden")])
    images = asyncio.run(fetch_artwork(result, guard=guard))
    assert len(images) == 1 and "hidden" not in images[0]
    with Image.open(io.BytesIO(base64.b64decode(images[0]))) as normalized:
        assert normalized.format == "JPEG" and normalized.width <= 480 and normalized.height <= 320
    assert calls[0].headers["accept-encoding"] == "identity"
    assert "cookie" not in calls[0].headers


def test_artwork_stops_large_stream_and_rejects_redirect(monkeypatch):
    chunks = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index in range(100):
                chunks.append(index)
                yield b"x" * 65536

    async def handle(request):
        return httpx.Response(200, headers={"Content-Type": "image/png"}, stream=Stream())

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handle))
    )

    async def allow(request):
        pass

    result = ImageParseResult(photo=[ImageRef(url="https://cdn.example/image")])
    assert asyncio.run(fetch_artwork(result, guard=allow)) == []
    assert len(chunks) <= 32

    async def deny(request):
        raise ValueError("blocked private address")

    chunks.clear()
    assert asyncio.run(fetch_artwork(result, guard=deny)) == []
    assert not chunks
    assert normalize_image(b"not an image") is None


def test_diagnostics_omit_sources_paths_credentials_and_snapshots(tmp_path):
    store = Store(tmp_path / "tasks.db")
    try:
        task_id = store.create("https://www.douyin.com/video/123?token=source-secret", str(tmp_path))
        store.set_setting("douyin.cookie", "cookie-secret")
        store.set_setting("douyin.proxy", "proxy-secret")
        store.update(task_id, title="title-secret", error="error-secret")
        store.db.execute("UPDATE attempts SET config_snapshot=?", ('{"cookie":"snapshot-secret"}',))
        store.db.commit()
        exported = json.dumps(diagnostic_report(store, resolve_engine()))
        for value in (
            "source-secret",
            "cookie-secret",
            "proxy-secret",
            "snapshot-secret",
            "title-secret",
            "error-secret",
            str(tmp_path),
            "https://",
        ):
            assert value not in exported
        assert task_id in exported
    finally:
        store.close()


def test_retry_failed_inspect_does_not_start_unconfirmed_download(tmp_path):
    store = Store(tmp_path / "tasks.db")
    try:
        task_id = store.create("https://www.douyin.com/video/123", str(tmp_path))
        task = store.get(task_id)
        assert store.transition(task_id, task["attempt_id"], "failed")
        assert store.retry(task_id)
        assert store.get(task_id)["action"] == "inspect"
        assert store.attempts(task_id)[-1]["action"] == "inspect"
    finally:
        store.close()


def test_ui_keyboard_themes_and_responsive_layout(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/check_m3_ui.py"
    env = dict(os.environ, QT_SCALE_FACTOR="1")
    subprocess.run(
        [sys.executable, str(script), "--output", str(tmp_path / "ui")],
        check=True,
        env=env,
        timeout=30,
        capture_output=True,
    )


def test_progress_unknown_totals_do_not_invent_percent_or_speed():
    assert progress_text({"kind": "bytes", "completed_bytes": 1024, "total_bytes": None}) == "1.0 KiB"
    assert progress_text({"kind": "count", "completed_items": 2, "total_items": 4}) == "2 / 4 项"
    assert progress_text({"kind": "percent", "percent": 35}) == "35%"


def test_history_removal_cleans_only_owned_temp_and_keeps_download(local_engine, tmp_path):
    app, store, service = local_engine
    task_id = service.submit(["https://www.douyin.com/video/950"], str(tmp_path))[0]
    wait_for(app, lambda: store.get(task_id)["state"] == "ready" and not service.running)
    service.retry(task_id)
    wait_for(app, lambda: store.get(task_id)["state"] == "completed" and not service.running)
    final = Path(store.get(task_id)["final_dir"])
    assert service.remove_history(task_id)
    wait_for(app, lambda: store.get(task_id) is None)
    assert (final / "001_本地下载验证.jpg").read_bytes() == b"local-media"
    assert not store.attempts(task_id)


def test_redownload_completed_keeps_preview_identity(local_engine, tmp_path):
    app, store, service = local_engine
    task_id = service.submit(["https://www.douyin.com/video/951"], str(tmp_path))[0]
    wait_for(app, lambda: store.get(task_id)["state"] == "ready" and not service.running)
    service.retry(task_id)
    wait_for(app, lambda: store.get(task_id)["state"] == "completed" and not service.running)
    service.retry(task_id)
    new_id = next(t["id"] for t in store.tasks() if t["id"] != task_id)
    wait_for(app, lambda: store.get(new_id)["state"] == "completed" and not service.running)
    assert store.get(task_id)["final_dir"] != store.get(new_id)["final_dir"]
    assert store.get(new_id)["preview"] and store.get(task_id)["state"] == "completed"


def test_record_removal_waits_for_cleanup(tmp_path):
    store = Store(tmp_path / "tasks.db")
    try:
        task_id = store.create("https://www.douyin.com/video/952", str(tmp_path))
        task = store.get(task_id)
        work = create_work_directory(tmp_path, task_id, task["attempt_id"])
        store.db.execute("UPDATE attempts SET work_dir=? WHERE id=?", (str(work), task["attempt_id"]))
        store.db.commit()
        store.transition(task_id, task["attempt_id"], "failed")
        store.request_history_cleanup(task_id)
        assert not store.remove_history(task_id)
        assert store.get(task_id) is not None and work.is_dir()
    finally:
        store.close()
