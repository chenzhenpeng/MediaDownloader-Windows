"""Read the selected core's capabilities without importing its SDK into the UI."""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from . import PROTOCOL
from .contracts import PLATFORM_HOSTS

MEDIA_NAMES = {
    "video": "视频",
    "image": "图片 / 图集",
    "music": "音频",
    "audio": "音频",
    "article": "图文 / Markdown 正文",
    "text": "文本",
}


def capability_copy(description, engine_version):
    if description.get("protocol") != PROTOCOL or description.get("engine_version") != engine_version:
        raise ValueError("Incompatible description")
    rows = []
    seen = set()
    for item in description.get("capabilities", []):
        platform = item.get("id")
        if platform not in PLATFORM_HOSTS or platform in seen or not item.get("available", False):
            continue
        seen.add(platform)
        name = item.get("name")
        if not isinstance(name, str) or not name or len(name) > 64:
            raise ValueError("Invalid platform name")
        types = list(
            dict.fromkeys(MEDIA_NAMES[kind] for kind in item.get("media_types", []) if kind in MEDIA_NAMES)
        )
        if item.get("live_photos"):
            types.append("实况照片")
        if types:
            rows.append((name, "、".join(types)))
    return rows


class CapabilityReader(QObject):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.failed)

    def refresh(self, engine):
        self.shutdown()
        self.changed.emit(None)
        self.engine_version = engine.version
        self.buffer = bytearray()
        process = self.process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUTF8", "1")
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(self.read)
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.finished.connect(self.finished)
        process.errorOccurred.connect(lambda error: self.failed())
        self.timer.start(20000)
        process.start(engine.program, [*engine.arguments, "--describe"])

    def read(self):
        if self.process is not None:
            self.buffer.extend(bytes(self.process.readAllStandardOutput()))
            if len(self.buffer) > 1024 * 1024:
                self.failed()

    def finished(self, code, status):
        self.timer.stop()
        self.read()
        if self.process is None:
            return
        try:
            if code != 0 or status != QProcess.ExitStatus.NormalExit:
                raise ValueError("Probe failed")
            rows = capability_copy(json.loads(self.buffer.decode("utf-8")), self.engine_version)
        except (ValueError, TypeError, AttributeError, KeyError):
            rows = []
        self.changed.emit(rows)

    def failed(self):
        self.shutdown()
        self.changed.emit([])

    def shutdown(self):
        self.timer.stop()
        process, self.process = self.process, None
        if process is not None:
            process.blockSignals(True)
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(1000)
            process.deleteLater()
