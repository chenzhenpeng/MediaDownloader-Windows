import io
import json
import sys

from media_downloader import PROTOCOL, worker


def test_protocol_forces_utf8_when_parent_stream_uses_windows_codepage(monkeypatch, tmp_path):
    command = {
        "protocol": PROTOCOL,
        "action": "inspect",
        "task_id": "t",
        "attempt_id": "a",
        "source": "https://www.douyin.com/video/123",
        "output_root": str(tmp_path),
    }
    data = io.BytesIO()
    output = io.TextIOWrapper(data, encoding="gbk")
    incoming = io.TextIOWrapper(io.BytesIO(json.dumps(command).encode("utf-8")), encoding="gbk")
    errors = io.TextIOWrapper(io.BytesIO(), encoding="gbk")

    async def fake_execute(received):
        worker.emit(received, "ready", {"title": "中文作品🧪"})

    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(sys, "stderr", errors)
    monkeypatch.setattr(sys, "stdin", incoming)
    monkeypatch.setattr(sys, "argv", ["media-engine.exe"])
    monkeypatch.setattr(worker, "WIRE", output)
    monkeypatch.setattr(worker, "execute", fake_execute)
    assert worker.main() == 0
    output.flush()
    assert json.loads(data.getvalue().decode("utf-8"))["payload"]["title"] == "中文作品🧪"
