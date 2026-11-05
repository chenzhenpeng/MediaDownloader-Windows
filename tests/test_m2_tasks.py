import hashlib
import json
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication
from test_worker_integration import MediaServer, wait_for

from media_downloader.engine import resolve_engine
from media_downloader.repository import Store
from media_downloader.service import TaskService
from media_downloader.task_files import (
    atomic_json,
    build_manifest,
    cleanup_work_directory,
    create_work_directory,
    verify_output,
)
from media_downloader.windows import protect


@pytest.fixture
def local_engine(tmp_path, monkeypatch):
    server = threading.Thread
    from http.server import ThreadingHTTPServer

    http = ThreadingHTTPServer(("127.0.0.1", 0), MediaServer)
    thread = server(target=http.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TEST_MEDIA_URL", f"http://127.0.0.1:{http.server_port}/test.jpg")
    store = Store(tmp_path / "tasks.db")
    service = TaskService(
        store,
        max_workers=1,
        engine_command=(sys.executable, [str(Path(__file__).with_name("fixture_engine.py"))]),
    )
    yield QCoreApplication.instance(), store, service
    service.shutdown()
    store.close()
    http.shutdown()
    http.server_close()
    thread.join()


def test_worker_reuse_preserves_attempts_hashes_and_removes_only_work_dir(local_engine, tmp_path):
    app, store, service = local_engine
    task_id = service.submit(["https://www.douyin.com/video/101"], str(tmp_path))[0]
    wait_for(app, lambda: store.get(task_id)["state"] == "ready" and not service.running)
    initial_pid = store.attempts(task_id)[0]["worker_pid"]
    service.retry(task_id)
    wait_for(app, lambda: store.get(task_id)["state"] == "completed" and not service.running)
    attempts = store.attempts(task_id)
    assert [item["state"] for item in attempts] == ["ready", "completed"]
    assert {item["worker_pid"] for item in attempts} == {initial_pid}
    assert attempts[0]["id"] != attempts[1]["id"] and attempts[1]["commit_token"]
    outputs = store.db.execute("SELECT * FROM outputs WHERE attempt_id=?", (attempts[1]["id"],)).fetchall()
    assert outputs[0]["sha256"] == hashlib.sha256(b"local-media").hexdigest()
    output = Path(store.get(task_id)["final_dir"])
    wait_for(app, lambda: not Path(attempts[1]["work_dir"]).exists())
    assert output.is_dir() and (output / "manifest.json").is_file()
    next_id = service.submit(["https://www.douyin.com/video/102"], str(tmp_path))[0]
    wait_for(app, lambda: store.get(next_id)["state"] == "ready" and not service.running)
    assert store.attempts(next_id)[0]["worker_pid"] == initial_pid


def test_every_platform_worker_preview_download_commit_and_article(local_engine, tmp_path, monkeypatch):
    from test_platform_catalog import SAMPLES

    from media_downloader.storage import PLATFORM_FOLDERS

    app, store, service = local_engine
    monkeypatch.setenv("TEST_ARTICLE_PLATFORM", "medium")
    store.set_setting("zhihu.cookie", protect("test=fixture").hex())
    store.set_setting("weixin_channels.cookie", protect("test=fixture").hex())
    ids = service.submit(list(SAMPLES.values()), str(tmp_path))
    wait_for(
        app, lambda: not service.running and all(store.get(i)["state"] == "ready" for i in ids), timeout=40
    )
    for task_id in ids:
        service.retry(task_id)
    wait_for(
        app,
        lambda: not service.running and all(store.get(i)["state"] == "completed" for i in ids),
        timeout=40,
    )
    for task_id in ids:
        task = store.get(task_id)
        final = Path(task["final_dir"])
        assert final.parent.name == PLATFORM_FOLDERS[task["platform"]]
        manifest = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["commit_token"] and manifest["files"]
        if task["platform"] == "medium":
            assert (final / "正文.md").read_text(encoding="utf-8").startswith("# 本地文章")
        else:
            assert (final / "001_本地下载验证.jpg").read_bytes() == b"local-media"


def test_active_source_deduplication_and_fifo(local_engine, tmp_path, monkeypatch):
    app, store, service = local_engine
    monkeypatch.setenv("TEST_DELAY", "0.2")
    sources = [f"https://www.douyin.com/video/{number}" for number in (201, 202, 203)]
    ids = service.submit([sources[0], sources[0] + "?tracking=x", *sources[1:]], str(tmp_path))
    assert len(ids) == 3 and len(store.tasks()) == 3
    wait_for(
        app, lambda: all(store.get(task_id)["state"] == "ready" for task_id in ids) and not service.running
    )
    starts = [store.attempts(task_id)[0]["started_at"] for task_id in ids]
    assert starts == sorted(starts)
    assert len({store.attempts(task_id)[0]["worker_pid"] for task_id in ids}) == 1


def test_crashed_worker_is_replaced_without_losing_queued_work(local_engine, tmp_path, monkeypatch):
    app, store, service = local_engine
    monkeypatch.setenv("TEST_CRASH_ID", "301")
    ids = service.submit(
        ["https://www.douyin.com/video/301", "https://www.douyin.com/video/302"], str(tmp_path)
    )
    wait_for(app, lambda: store.get(ids[0])["state"] == "interrupted")
    wait_for(app, lambda: store.get(ids[1])["state"] == "ready" and not service.running)
    assert store.attempts(ids[0])[0]["state"] == "interrupted"
    assert store.attempts(ids[0])[0]["worker_pid"] != store.attempts(ids[1])[0]["worker_pid"]


def test_cooperative_cancel_has_terminal_history(local_engine, tmp_path, monkeypatch):
    app, store, service = local_engine
    monkeypatch.setenv("TEST_DELAY", "10")
    task_id = service.submit(["https://www.douyin.com/video/401"], str(tmp_path))[0]
    wait_for(app, lambda: task_id in service.running)
    service.cancel(task_id)
    wait_for(app, lambda: store.get(task_id)["state"] == "cancelled" and not service.running)
    assert store.attempts(task_id)[0]["finished_at"]
    assert store.attempts(task_id)[0]["state"] == "cancelled"


def test_connection_snapshot_is_encrypted_and_does_not_change_mid_attempt(
    local_engine, tmp_path, monkeypatch
):
    app, store, service = local_engine
    old, new = protect("session=old").hex(), protect("session=new").hex()
    store.set_setting("douyin.cookie", old)
    monkeypatch.setenv("TEST_DELAY", "0.5")
    monkeypatch.setenv("TEST_COOKIE_EXPECTED", "session=old")
    task_id = service.submit(["https://www.douyin.com/video/501"], str(tmp_path))[0]
    wait_for(app, lambda: task_id in service.running)
    store.set_setting("douyin.cookie", new)
    wait_for(app, lambda: store.get(task_id)["state"] == "ready" and not service.running)
    snapshot = store.attempts(task_id)[0]["config_snapshot"]
    assert json.loads(snapshot)["cookie"] == old
    assert "session=old" not in snapshot and store.setting("douyin.cookie") == new


def committed_fixture(store, root):
    task_id = store.create("https://www.douyin.com/video/601", str(root), "download")
    task = store.get(task_id)
    attempt = task["attempt_id"]
    work = create_work_directory(root, task_id, attempt)
    assert store.start(task_id, resolve_engine(), 123, {}, work)
    assert store.transition(task_id, attempt, "downloading")
    output = work / "payload"
    output.mkdir()
    (output / "video.mp4").write_bytes(b"verified output")
    final = root / "抖音" / f"title_{task_id[:8]}_{attempt[:6]}"
    final.parent.mkdir()
    token = store.authorize_commit(task_id, attempt, str(final))
    command = {"output_root": str(root), "task_id": task_id, "attempt_id": attempt}
    manifest = build_manifest(output, command, {}, "test", "test")
    manifest["commit_token"] = token
    atomic_json(output / "manifest.json", manifest)
    output.rename(final)
    return task_id, attempt, final, token


def test_restart_recovers_committed_files_before_marking_complete(tmp_path):
    path = tmp_path / "tasks.db"
    store = Store(path)
    task_id, attempt, final, token = committed_fixture(store, tmp_path)
    store.close()
    store = Store(path)
    service = TaskService(store)
    try:
        wait_for(QCoreApplication.instance(), lambda: store.get(task_id)["state"] == "completed")
        assert (
            store.db.execute("SELECT count(*) FROM outputs WHERE attempt_id=?", (attempt,)).fetchone()[0] == 1
        )
        assert verify_output(tmp_path, str(final), task_id, attempt, token)["files"]
    finally:
        service.shutdown()
        store.close()


def test_tampered_commit_is_interrupted_and_never_deleted(tmp_path):
    path = tmp_path / "tasks.db"
    store = Store(path)
    task_id, _, final, _ = committed_fixture(store, tmp_path)
    (final / "video.mp4").write_bytes(b"tampered output")
    store.close()
    store = Store(path)
    service = TaskService(store)
    try:
        wait_for(QCoreApplication.instance(), lambda: store.get(task_id)["state"] == "interrupted")
        assert final.is_dir() and (final / "video.mp4").read_bytes() == b"tampered output"
    finally:
        service.shutdown()
        store.close()


def test_cancel_and_commit_are_mutually_exclusive_and_old_attempt_cannot_change_new_one(tmp_path):
    store = Store(tmp_path / "tasks.db")
    task_id = store.create("https://www.douyin.com/video/701", str(tmp_path))
    task = store.get(task_id)
    old = task["attempt_id"]
    assert store.transition(task_id, old, "parsing")
    assert store.transition(task_id, old, "downloading")
    assert store.transition(task_id, old, "cancelling")
    assert store.authorize_commit(task_id, old, str(tmp_path / "final")) is None
    assert store.transition(task_id, old, "cancelled")
    assert store.retry(task_id)
    assert not store.transition(task_id, old, "completed")
    assert store.get(task_id)["state"] == "queued"
    assert len(store.attempts(task_id)) == 2
    store.close()


def test_commit_transaction_rolls_back_state_when_token_cannot_be_saved(tmp_path):
    store = Store(tmp_path / "tasks.db")
    task_id = store.create("https://www.douyin.com/video/702", str(tmp_path))
    attempt = store.get(task_id)["attempt_id"]
    assert store.transition(task_id, attempt, "parsing")
    assert store.transition(task_id, attempt, "downloading")
    store.db.execute("""CREATE TRIGGER reject_token BEFORE UPDATE OF commit_token ON attempts
        BEGIN SELECT RAISE(ABORT, 'test token failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        store.authorize_commit(task_id, attempt, str(tmp_path / "output"))
    assert store.get(task_id)["state"] == "downloading"
    assert store.attempt(attempt)["commit_token"] == ""
    store.close()


def test_waiting_preview_cancel_preserves_successful_inspect_history(local_engine, tmp_path):
    app, store, service = local_engine
    task_id = service.submit(["https://www.douyin.com/video/703"], str(tmp_path))[0]
    wait_for(app, lambda: store.get(task_id)["state"] == "ready" and not service.running)
    service.cancel(task_id)
    assert store.get(task_id)["state"] == "cancelled"
    assert store.attempts(task_id)[0]["state"] == "ready"


@pytest.mark.parametrize("version", [2, 99])
def test_noncurrent_schema_is_rejected_without_migration(tmp_path, version):
    path = tmp_path / "tasks.db"
    store = Store(path)
    task_id = store.create("https://www.douyin.com/video/704", str(tmp_path))
    store.db.execute(f"PRAGMA user_version={version}")
    store.close()
    with pytest.raises(RuntimeError, match="数据库版本"):
        Store(path)
    with sqlite3.connect(path) as untouched:
        assert untouched.execute("PRAGMA user_version").fetchone()[0] == version
        assert untouched.execute("SELECT id FROM tasks").fetchone()[0] == task_id
    assert not list(tmp_path.glob("*.bak"))


def test_two_workers_bound_concurrency_and_queue_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MEDIA_URL", "http://127.0.0.1:1/not-downloaded")
    monkeypatch.setenv("TEST_DELAY", "0.3")
    path = tmp_path / "tasks.db"
    store = Store(path)
    ids = [store.create(f"https://www.douyin.com/video/{800 + i}", str(tmp_path)) for i in range(5)]
    store.close()
    store = Store(path)
    assert all(store.get(task_id)["state"] == "queued" for task_id in ids)
    service = TaskService(
        store,
        max_workers=2,
        engine_command=(sys.executable, [str(Path(__file__).with_name("fixture_engine.py"))]),
    )
    peak = 0
    app = QCoreApplication.instance()
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            app.processEvents()
            peak = max(peak, len(service.running))
            if all(store.get(task_id)["state"] == "ready" for task_id in ids) and not service.running:
                break
            time.sleep(0.01)
        assert peak == 2
        assert all(store.get(task_id)["state"] == "ready" for task_id in ids)
        assert len({store.attempts(task_id)[0]["worker_pid"] for task_id in ids}) == 2
    finally:
        service.shutdown()
        store.close()


def test_heartbeat_timeout_interrupts_attempt_and_kills_worker(tmp_path):
    store = Store(tmp_path / "tasks.db")
    code = (
        "import sys,json,time; from media_downloader import PROTOCOL,ENGINE_VERSION,UPSTREAM_SHA; "
        "print(json.dumps({'protocol':PROTOCOL,'type':'worker_ready','payload':"
        "{'engine_version':ENGINE_VERSION,'upstream_sha':UPSTREAM_SHA}}),flush=True); "
        "sys.stdin.readline(); time.sleep(60)"
    )
    service = TaskService(
        store, max_workers=1, heartbeat_timeout=0.3, engine_command=(sys.executable, ["-c", code])
    )
    try:
        task_id = service.submit(["https://www.douyin.com/video/901"], str(tmp_path))[0]
        wait_for(
            QCoreApplication.instance(),
            lambda: store.get(task_id)["state"] == "interrupted" and not service.running,
        )
        assert store.get(task_id)["error_code"] == "WORKER_TIMEOUT"
        assert store.attempts(task_id)[0]["state"] == "interrupted"
    finally:
        service.shutdown()
        store.close()


def test_cleanup_refuses_unowned_marker_and_directory_junction(tmp_path):
    task, attempt = "a" * 32, "b" * 32
    work = create_work_directory(tmp_path, task, attempt)
    (work / "owner.json").write_text("{}")
    with pytest.raises(ValueError):
        cleanup_work_directory(tmp_path, task, attempt)
    atomic_json(work / "owner.json", {"task_id": task, "attempt_id": attempt})
    outside = tmp_path / "keep"
    outside.mkdir()
    (outside / "important.txt").write_text("keep")
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(work / "redirect"), str(outside)], capture_output=True
    )
    assert result.returncode == 0
    with pytest.raises(ValueError):
        cleanup_work_directory(tmp_path, task, attempt)
    assert (outside / "important.txt").read_text() == "keep"


def test_cleanup_can_retry_after_payload_sharing_violation(tmp_path, monkeypatch):
    import media_downloader.task_files as task_files

    task, attempt = "c" * 32, "d" * 32
    work = create_work_directory(tmp_path, task, attempt)
    payload = work / "payload"
    payload.mkdir()
    (payload / "media.mp4").write_bytes(b"data")
    original = task_files.shutil.rmtree

    def locked(*args, **kwargs):
        raise PermissionError("simulated sharing violation")

    monkeypatch.setattr(task_files.shutil, "rmtree", locked)
    with pytest.raises(PermissionError):
        cleanup_work_directory(tmp_path, task, attempt)
    assert (work / "owner.json").is_file()
    monkeypatch.setattr(task_files.shutil, "rmtree", original)
    assert cleanup_work_directory(tmp_path, task, attempt)
    assert not work.exists()


def test_platform_cooldown_does_not_block_other_platform(local_engine, tmp_path):
    app, store, service = local_engine
    service.cooldown["douyin"] = time.time() + 60
    ids = service.submit(
        ["https://www.douyin.com/video/902", "https://www.bilibili.com/video/BV123"], str(tmp_path)
    )
    wait_for(app, lambda: store.get(ids[1])["state"] == "ready" and not service.running)
    assert store.get(ids[0])["state"] == "queued"
    service.cooldown["douyin"] = 0
    wait_for(app, lambda: store.get(ids[0])["state"] == "ready" and not service.running)


def test_first_native_import_keeps_heartbeat_and_cooperative_cancel(tmp_path):
    app = QCoreApplication.instance()
    store = Store(tmp_path / "tasks.db")
    service = TaskService(
        store,
        max_workers=1,
        engine_command=(sys.executable, [str(Path(__file__).with_name("lazy_fixture_engine.py"))]),
    )
    try:
        task_id = service.submit(["https://www.douyin.com/video/903"], str(tmp_path))[0]
        wait_for(app, lambda: bool(service.running))
        began = time.monotonic()
        wait_for(app, lambda: time.monotonic() - began > 4)
        assert store.get(task_id)["state"] == "parsing"
        slot = service.running[task_id]["slot"]
        assert time.monotonic() - slot.last_seen < 2.5
        service.cancel(task_id)
        wait_for(app, lambda: store.get(task_id)["state"] == "cancelled" and not service.running)
        assert not store.get(task_id).get("error_code")
    finally:
        service.shutdown()
        store.close()
