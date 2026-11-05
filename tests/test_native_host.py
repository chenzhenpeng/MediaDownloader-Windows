import json
import threading
from types import SimpleNamespace

from media_downloader.desktop_host import DesktopHost
from media_downloader.repository import Store


def test_download_preparation_keeps_confirmed_preview(tmp_path):
    store = Store(tmp_path / "tasks.db")
    try:
        task_id = store.create("https://www.douyin.com/video/1", str(tmp_path))
        preview = {"resource_id": "work-1", "thumbnails": ["fixture-artwork"], "media": []}
        store.update(task_id, state="ready", title="Confirmed work", preview=json.dumps(preview))
        host = DesktopHost.__new__(DesktopHost)
        host.service = SimpleNamespace(progress={}, running={})
        host.sent_thumbnails, host.visible_thumbnails = {}, set()
        ready = host.public_task(store.get(task_id), {})
        assert ready["has_preview"] and ready["thumbnail"] == "fixture-artwork"
        assert store.retry(task_id)
        for state in ("queued", "parsing", "downloading"):
            store.update(task_id, state=state)
            task = host.public_task(store.get(task_id), {})
            assert task["action"] == "download" and task["has_preview"]
            assert task["title"] == ready["title"]
            assert task["thumbnail"] is None  # Existing artwork remains valid in the client.
            assert json.loads(store.get(task_id)["preview"]) == preview
    finally:
        store.close()


def test_snapshot_is_paginated_and_does_not_expose_credentials(tmp_path):
    store = Store(tmp_path / "tasks.db")
    try:
        ids = [store.create(f"https://www.douyin.com/video/{i}", str(tmp_path)) for i in range(55)]
        store.set_setting("douyin.cookie", "private-cookie-value")
        store.set_setting("douyin.proxy", "private-proxy-value")
        host = DesktopHost.__new__(DesktopHost)
        host.store = store
        host.service = SimpleNamespace(progress={}, running={}, engine=SimpleNamespace(version="test"))
        host.updates = SimpleNamespace(
            engines=SimpleNamespace(state=lambda: {"current": "bundled", "last_good": "bundled"}),
            status="idle",
            message="",
            busy=False,
            feed=SimpleNamespace(trust=SimpleNamespace(configured=False)),
        )
        # Match the update-manager interface used by the presentation snapshot.
        host.updates.engines.trust = SimpleNamespace(configured=False)
        host.available = set()
        host.view = {"scope": "active", "query": "", "state": "", "offset": 0}
        host.detail_id = ""
        host.submitted_ids = set()
        host.sent_thumbnails = {}
        host.visible_thumbnails = set()
        first = host.snapshot()
        assert first["total"] == 55 and len(first["tasks"]) == 50
        encoded = json.dumps(first)
        assert "private-cookie-value" not in encoded and "private-proxy-value" not in encoded
        host.updates.progress = (400, 1000)
        host.updates.cancelled = threading.Event()
        host.updates.cancelled.set()
        host.updates.busy = True
        progress = host.snapshot()["update"]
        assert (progress["downloaded_bytes"], progress["total_bytes"]) == (400, 1000)
        assert progress["cancel_requested"]
        assert all("source" not in task and "config" not in task for task in first["tasks"])
        host.view["offset"] = 50
        second = host.snapshot()
        assert len(second["tasks"]) == 5
        assert {t["id"] for t in first["tasks"]}.isdisjoint(t["id"] for t in second["tasks"])
        assert set(host.sent_thumbnails) == {t["id"] for t in second["tasks"]}
        assert set(ids) == {t["id"] for t in first["tasks"] + second["tasks"]}
        states = [
            "ready",
            "downloading",
            "finalizing",
            "completed",
            "failed",
            "cancelled",
            "interrupted",
            "cancelling",
            "parsing",
        ]
        for task_id, state in zip(ids, states, strict=False):
            store.update(task_id, state=state, title=f"selected-{state}")
        host.view = {"scope": "all", "query": "selected-", "state": "", "offset": 0}
        combined = host.snapshot()
        assert {t["state"] for t in combined["tasks"]} == set(states)
        host.view["state"] = "active"
        assert {t["state"] for t in host.snapshot()["tasks"]} == {
            "ready",
            "downloading",
            "finalizing",
            "cancelling",
            "parsing",
        }
        for state in ("completed", "failed"):
            host.view["state"] = state
            filtered = host.snapshot()
            assert filtered["total"] == 1 and filtered["tasks"][0]["state"] == state
        host.handle("connection", {"platform": "douyin", "cookie": "fixture-cookie=value"})
        saved = store.setting("douyin.cookie")
        assert "fixture-cookie" not in saved
        assert host.handle("connection_read", {"platform": "douyin"}) == {"cookie": "fixture-cookie=value"}
        assert host.handle("connection_read", {"platform": "xhs"}) == {"cookie": ""}
        assert "fixture-cookie" not in json.dumps(host.snapshot())
        host.handle("connection", {"platform": "douyin", "cookie": ""})
        assert store.setting("douyin.cookie") == saved
        host.handle("connection", {"platform": "douyin", "clear_cookie": True})
        assert host.handle("connection_read", {"platform": "douyin"}) == {"cookie": ""}
    finally:
        store.close()
