import ctypes
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from media_downloader.service import TaskService
from media_downloader.storage import Store


class MediaServer(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", "11")
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "11")
        self.end_headers()
        self.wfile.write(b"local-media")


def wait_for(app, predicate, timeout=15):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for worker")


def test_real_worker_download_commit_and_preview(tmp_path, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    server = ThreadingHTTPServer(("127.0.0.1", 0), MediaServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TEST_MEDIA_URL", f"http://127.0.0.1:{server.server_port}/test.jpg")
    store = Store(tmp_path / "tasks.db")
    service = TaskService(
        store, engine_command=(sys.executable, [str(Path(__file__).with_name("fixture_engine.py"))])
    )
    try:
        service.submit(["https://www.douyin.com/video/123"], str(tmp_path))
        task_id = store.tasks()[0]["id"]
        wait_for(app, lambda: store.get(task_id)["state"] == "ready" and not service.running)
        service.retry(task_id)
        wait_for(app, lambda: store.get(task_id)["state"] == "completed" and not service.running)
        output = Path(store.get(task_id)["final_dir"])
        assert (output / "001_本地下载验证.jpg").read_bytes() == b"local-media"
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["attempt_id"] == store.get(task_id)["attempt_id"]
        assert manifest["files"][0]["size"] == 11
    finally:
        service.shutdown()
        store.close()
        server.shutdown()
        server.server_close()
        thread.join()


def test_cancel_stops_worker_process_tree(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    store = Store(tmp_path / "tasks.db")
    child_pid = tmp_path / "child.pid"
    code = (
        "import sys,subprocess,time,json; from pathlib import Path; "
        "from media_downloader import PROTOCOL,ENGINE_VERSION,UPSTREAM_SHA; "
        "print(json.dumps({'protocol':PROTOCOL,'type':'worker_ready','payload':"
        "{'engine_version':ENGINE_VERSION,'upstream_sha':UPSTREAM_SHA}}),flush=True); "
        "sys.stdin.readline(); "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],"
        "creationflags=0x08000000); "
        f"Path({str(child_pid)!r}).write_text(str(child.pid)); time.sleep(60)"
    )
    service = TaskService(store, engine_command=(sys.executable, ["-c", code]))
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    child_handle = None
    try:
        service.submit(["https://www.douyin.com/video/123"], str(tmp_path))
        task_id = store.tasks()[0]["id"]
        wait_for(app, child_pid.exists)
        child_handle = kernel.OpenProcess(0x1000, False, int(child_pid.read_text()))
        assert child_handle
        service.cancel(task_id)
        wait_for(app, lambda: not service.running)
        assert store.get(task_id)["state"] == "cancelled"
        status = ctypes.c_ulong()
        assert kernel.GetExitCodeProcess(child_handle, ctypes.byref(status))
        assert status.value != 259  # STILL_ACTIVE: a grandchild must also have exited.
    finally:
        service.shutdown()
        if child_handle:
            kernel.CloseHandle(child_handle)
        store.close()
