import json
import sqlite3

from PySide6.QtCore import QCoreApplication
from test_worker_integration import wait_for

from media_downloader.repository import Store
from media_downloader.service import TaskService
from media_downloader.storage import output_directory


def legacy_task(store, root):
    key = store.create("https://v.kuaishou.com/test", str(root))
    preview = {"media": [{"kind": "video", "duration_seconds": 282400}]}
    store.update(key, engine_version="0.1.0.platforms-dev9", preview=json.dumps(preview))
    return key


def test_known_legacy_duration_is_backed_up_and_repaired_once(tmp_path):
    path = tmp_path / "tasks.db"
    store = Store(path)
    key = legacy_task(store, tmp_path)
    store.close()
    store = Store(path)
    assert json.loads(store.get(key)["preview"])["media"][0]["duration_seconds"] == 282.4
    backup = path.with_name(path.name + ".pre-history-repair-v1.bak")
    with sqlite3.connect(backup) as db:
        old = json.loads(db.execute("SELECT preview FROM tasks WHERE id=?", (key,)).fetchone()[0])
        assert old["media"][0]["duration_seconds"] == 282400
    store.close()
    store = Store(path)
    assert json.loads(store.get(key)["preview"])["media"][0]["duration_seconds"] == 282.4
    store.close()


def test_current_duration_is_not_guessed_or_divided_again(tmp_path):
    path = tmp_path / "tasks.db"
    store = Store(path)
    key = legacy_task(store, tmp_path)
    store.update(key, engine_version="0.1.0.kuaishou-dev10")
    store.close()
    store = Store(path)
    assert json.loads(store.get(key)["preview"])["media"][0]["duration_seconds"] == 282400
    assert not path.with_name(path.name + ".pre-history-repair-v1.bak").exists()
    store.close()


def completed_output(store, root, content):
    key = store.create("https://v.kuaishou.com/test", str(root))
    task = store.get(key)
    final = output_directory(root, "kuaishou", "标题", key, task["attempt_id"])
    final.mkdir(parents=True)
    file = final / "video.mp4"
    file.write_bytes(content)
    store.update(key, state="completed", final_dir=str(final))
    store.db.execute("INSERT INTO outputs VALUES (?,?,?,NULL)", (task["attempt_id"], file.name, len(content)))
    store.db.commit()
    return key, file


def test_confirmed_invalid_completion_is_marked_failed_without_deleting_file(tmp_path):
    store = Store(tmp_path / "tasks.db")
    key, file = completed_output(store, tmp_path, b"#EXTM3U\n#EXTINF:5\na.ts\n")
    service = TaskService(store)
    try:
        wait_for(QCoreApplication.instance(), lambda: service.history_audit is None)
        assert store.get(key)["state"] == "failed"
        assert store.get(key)["error_code"] == "INVALID_SAVED_MEDIA"
        assert file.read_bytes().startswith(b"#EXTM3U")
        assert store.attempts(key)[0]["state"] == "completed"  # Preserve what the original run reported.
    finally:
        service.shutdown()
        store.close()


def test_audit_result_does_not_overwrite_new_attempt(tmp_path):
    store = Store(tmp_path / "tasks.db")
    key, file = completed_output(store, tmp_path, b"#EXTM3U\n")
    service = TaskService(store)
    try:
        service.dispatch_paused = True
        store.update(key, state="failed")
        assert store.retry(key)
        new_attempt = store.get(key)["attempt_id"]
        wait_for(QCoreApplication.instance(), lambda: service.history_audit is None)
        assert store.get(key)["attempt_id"] == new_attempt
        assert store.get(key)["error_code"] != "INVALID_SAVED_MEDIA"
        assert file.exists()
    finally:
        service.shutdown()
        store.close()


def test_missing_saved_file_is_not_called_corrupt(tmp_path):
    store = Store(tmp_path / "tasks.db")
    key, file = completed_output(store, tmp_path, b"valid fixture")
    file.unlink()
    service = TaskService(store)
    try:
        wait_for(QCoreApplication.instance(), lambda: service.history_audit is None)
        assert store.get(key)["state"] == "completed"
    finally:
        service.shutdown()
        store.close()
