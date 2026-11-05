from PySide6.QtCore import QCoreApplication
from test_worker_integration import wait_for

from media_downloader.repository import Store
from media_downloader.service import TaskService
from media_downloader.storage import output_directory


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
