from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QProcess, QProcessEnvironment, QTimer, Signal

from . import PROTOCOL
from .engine import resolve_engine
from .repository import Store
from .task_files import cleanup_work_directory, verify_output, work_directory
from .windows import ProcessJob, unprotect


@dataclass
class Slot:
    number: int
    process: QProcess | None = None
    job: ProcessJob | None = None
    state: str = "stopped"
    task_id: str | None = None
    buffer: bytes = b""
    last_seen: float = 0
    restart_after: float = 0
    failures: int = 0
    retiring: bool = False


class TaskService(QObject):
    changed = Signal()
    engine_activated = Signal(object)
    engine_switch_failed = Signal(str)
    engine_unhealthy = Signal()

    def __init__(
        self,
        store: Store,
        parent=None,
        engine_command=None,
        engine=None,
        max_workers=None,
        cancel_grace=2.0,
        heartbeat_timeout=15.0,
        startup_timeout=20.0,
    ):
        super().__init__(parent)
        self.store, self.engine_command = store, engine_command
        self.engine = engine or resolve_engine()
        self.running: dict[str, dict] = {}
        self.progress: dict[str, dict] = {}
        self.closing = False
        self.started_pool = False
        self.dispatching = False
        self.dispatch_paused = False
        self.switch_pending = None
        self.switching = False
        self.rollback_on_start_failure = False
        self.cancel_grace, self.heartbeat_timeout, self.startup_timeout = (
            cancel_grace,
            heartbeat_timeout,
            startup_timeout,
        )
        workers = store.setting("max_workers", 2) if max_workers is None else max_workers
        self.slots = [Slot(index) for index in range(max(1, min(4, int(workers))))]
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="media-files")
        self.verifications = []
        self.cleanups = {}
        self.pending_removals = set()
        from .output_audit import audit_outputs

        audit_jobs = [
            (
                task,
                [
                    r[0]
                    for r in store.db.execute(
                        "SELECT relative_path FROM outputs WHERE attempt_id=?", (task["attempt_id"],)
                    )
                ],
            )
            for task in store.tasks()
            if task["state"] == "completed"
        ]
        self.history_audit = self.executor.submit(audit_outputs, audit_jobs)
        self.cooldown = store.setting("platform_cooldown", {})
        for task in store.tasks():
            if task["state"] == "finalizing":
                self._verify(task, recovering=True)
            for attempt in store.attempts(task["id"]):
                if attempt["work_dir"] and attempt["state"] in {
                    "completed",
                    "failed",
                    "cancelled",
                    "interrupted",
                }:
                    store.schedule_cleanup(
                        attempt["id"], delay_days=0 if attempt["state"] in {"completed", "cancelled"} else 7
                    )
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def submit(self, sources, output_root):
        ids = [self.store.create(source, output_root, deduplicate=True) for source in sources]
        self.started_pool = True
        for slot in self.slots:
            if slot.failures >= 3:
                slot.failures, slot.restart_after = 0, 0
        self.changed.emit()
        self.dispatch()
        return list(dict.fromkeys(ids))

    def retry(self, task_id):
        task = self.store.get(task_id)
        if not task or task_id in self.running:
            return
        if task["state"] == "completed":
            new_id = self.store.create(
                self.store.source(task_id), task["output_root"], "download", deduplicate=True
            )
            new_task = self.store.get(new_id)
            if new_task["state"] == "queued" and not json.loads(new_task["preview"] or "{}").get(
                "resource_id"
            ):
                self.store.update(new_id, preview=task["preview"], title=task["title"])
        elif not self.store.retry(task_id):
            return
        self.started_pool = True
        self.progress.pop(task_id, None)
        for slot in self.slots:
            slot.failures, slot.restart_after = 0, 0
        self.changed.emit()
        self.dispatch()

    def _spawn(self, slot):
        process = QProcess(self)
        slot.process, slot.job, slot.buffer = process, None, b""
        slot.state, slot.retiring, slot.last_seen = "starting", False, time.monotonic()
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONDONTWRITEBYTECODE", "1")
        process.setProcessEnvironment(env)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.started.connect(lambda s=slot, p=process: self._process_started(s, p))
        process.readyReadStandardOutput.connect(lambda s=slot, p=process: self._read(s, p))
        process.readyReadStandardError.connect(lambda p=process: p.readAllStandardError())
        process.finished.connect(lambda code, status, s=slot, p=process: self._exited(s, p))
        process.errorOccurred.connect(lambda error, s=slot, p=process: self._process_error(s, p, error))
        program, arguments = self.engine_command or (self.engine.program, list(self.engine.arguments))
        process.start(program, [*arguments, "--serve"])

    def _process_started(self, slot, process):
        if slot.process is not process:
            return
        try:
            slot.job = ProcessJob(process.processId())
        except OSError:
            self._fault(slot, "PROCESS_JOB_FAILED")

    def _send(self, slot, message):
        if slot.process:
            slot.process.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))

    def dispatch(self):
        if (
            self.closing
            or self.dispatch_paused
            or self.dispatching
            or self.verifications
            and any(item[3] for item in self.verifications)
        ):
            return
        self.dispatching = True
        try:
            queued = self.store.queued()
            if queued:
                self.started_pool = True
            for slot in self.slots:
                if (
                    self.started_pool
                    and slot.process is None
                    and slot.failures < 3
                    and slot.restart_after <= time.monotonic()
                ):
                    self._spawn(slot)
            for task in queued:
                if self.cooldown.get(task["platform"], 0) > time.time():
                    continue
                slot = next(
                    (
                        s
                        for s in self.slots
                        if s.state == "idle"
                        and s.task_id is None
                        and not s.retiring
                        and s.process is not None
                        and s.process.state() == QProcess.ProcessState.Running
                    ),
                    None,
                )
                if slot is None:
                    break
                self._assign(slot, task)
            if queued and all(slot.failures >= 3 for slot in self.slots) and not self.running:
                if self.rollback_on_start_failure:
                    self.dispatch_paused = True
                    self.engine_unhealthy.emit()
                    return
                for task in queued:
                    self.store.transition(
                        task["id"],
                        task["attempt_id"],
                        "failed",
                        error="内核多次无法启动，请检查安装后重试。",
                        error_code="ENGINE_START_FAILED",
                    )
                self.changed.emit()
        finally:
            self.dispatching = False

    def _assign(self, slot, task):
        snapshot = {key: self.store.setting(f"{task['platform']}.{key}") for key in ("cookie", "proxy")}
        work = work_directory(task["output_root"], task["id"], task["attempt_id"])
        if not self.store.start(task["id"], self.engine, slot.process.processId(), snapshot, work):
            return
        slot.state, slot.task_id = "busy", task["id"]
        self.running[task["id"]] = {
            "slot": slot,
            "process": slot.process,
            "job": slot.job,
            "attempt_id": task["attempt_id"],
            "last_seq": 0,
            "terminal": False,
            "idle": False,
            "cancel_deadline": None,
            "verifying": False,
        }
        try:
            command = {
                "protocol": PROTOCOL,
                "task_id": task["id"],
                "attempt_id": task["attempt_id"],
                "action": task["action"],
                "source": self.store.source(task["id"]),
                "output_root": task["output_root"],
            }
            if task["action"] == "download":
                command["expected_resource_id"] = json.loads(task["preview"]).get("resource_id")
            for key in ("cookie", "proxy"):
                command[key] = unprotect(bytes.fromhex(snapshot[key])) if snapshot[key] else None
            self._send(slot, command)
        except (OSError, ValueError):
            self.store.transition(
                task["id"],
                task["attempt_id"],
                "failed",
                error="无法读取本次任务的加密连接配置。",
                error_code="CREDENTIAL_UNAVAILABLE",
            )
            self.running[task["id"]]["terminal"] = True
            self._retire(slot)
        self.changed.emit()

    def _read(self, slot, process):
        if slot.process is not process:
            return
        slot.buffer += bytes(process.readAllStandardOutput())
        visible_change = False
        if len(slot.buffer) > 1024 * 1024:
            self._fault(slot, "INVALID_PROTOCOL")
            return
        while b"\n" in slot.buffer:
            line, slot.buffer = slot.buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or event.get("protocol") != PROTOCOL:
                    raise ValueError("Invalid protocol")
                kind, data = event["type"], event["payload"]
                visible_change = visible_change or kind != "heartbeat"
                if kind == "worker_ready":
                    if (
                        slot.state != "starting"
                        or data["engine_version"] != self.engine.version
                        or data["upstream_sha"] != self.engine.upstream_sha
                    ):
                        raise ValueError("Engine mismatch")
                    slot.state, slot.last_seen = "idle", time.monotonic()
                    if self.switching:
                        self.switching = False
                        self.engine_activated.emit(self.engine)
                    self.dispatch()
                    continue
                if kind == "heartbeat":
                    slot.last_seen = time.monotonic()
                entry = self.running.get(slot.task_id)
                if (
                    not entry
                    or event.get("task_id") != slot.task_id
                    or event.get("attempt_id") != entry["attempt_id"]
                ):
                    continue
                seq = event.get("seq")
                if not isinstance(seq, int) or seq <= entry["last_seq"]:
                    continue
                entry["last_seq"], slot.last_seen = seq, time.monotonic()
                self._event(slot, entry, event)
            except (ValueError, KeyError, TypeError):
                self._fault(slot, "INVALID_PROTOCOL")
                break
        if visible_change:
            self.changed.emit()

    def _event(self, slot, entry, event):
        task = self.store.get(slot.task_id)
        if not task or task["attempt_id"] != entry["attempt_id"]:
            return
        kind, data = event["type"], event["payload"]
        if kind == "idle":
            entry["idle"] = True
            if task["state"] == "cancelling":
                entry["terminal"] = True
                self._retire(slot)
                return
            if not entry["terminal"] and not entry["verifying"]:
                self._fault(slot, "MISSING_RESULT")
            else:
                self._release(slot)
            return
        if task["state"] == "cancelling":
            if kind == "cancelled":
                entry["terminal"] = True
                self._retire(slot)
            return
        if kind == "started":
            if (
                data["engine_version"] != self.engine.version
                or data["upstream_sha"] != self.engine.upstream_sha
            ):
                raise ValueError("Engine mismatch")
        elif kind == "preview":
            previous = json.loads(task["preview"] or "{}")
            if "thumbnails" not in data and previous.get("resource_id") == data.get("resource_id"):
                data["thumbnails"] = previous.get("thumbnails", [])
            self.store.update(
                task["id"],
                title=data["title"],
                platform=data["platform"],
                preview=json.dumps(data, ensure_ascii=False),
            )
        elif kind == "progress" and task["state"] == "downloading":
            self.progress[task["id"]] = data
        elif kind in {"ready", "downloading"}:
            if self.store.transition(task["id"], entry["attempt_id"], kind):
                entry["terminal"] = kind == "ready"
        elif kind == "commit_requested":
            from .storage import valid_output_directory

            final = Path(data["final_dir"])
            if not valid_output_directory(task["output_root"], final, task["id"], entry["attempt_id"]):
                raise ValueError("Invalid output")
            token = self.store.authorize_commit(task["id"], entry["attempt_id"], str(final))
            if token:
                self._send(
                    slot,
                    {
                        "type": "authorize_commit",
                        "task_id": task["id"],
                        "attempt_id": entry["attempt_id"],
                        "commit_token": token,
                    },
                )
        elif kind == "completed" and task["state"] == "finalizing":
            if data["final_dir"] != task["final_dir"]:
                raise ValueError("Unexpected output")
            self._verify(task)
        elif kind == "failed":
            if self.store.transition(
                task["id"],
                entry["attempt_id"],
                "failed",
                error=data["message"],
                error_code=data.get("code", "ENGINE_ERROR"),
            ):
                entry["terminal"] = True
                if data.get("code") == "RATE_LIMITED":
                    self.cooldown[task["platform"]] = time.time() + 60
                    self.store.set_setting("platform_cooldown", self.cooldown)
                self._retire(slot)

    def _verify(self, task, *, recovering=False):
        attempt = self.store.attempt(task["attempt_id"])
        if any(item[0]["attempt_id"] == task["attempt_id"] for item in self.verifications):
            return
        entry = self.running.get(task["id"])
        if entry:
            entry["verifying"] = True
            entry["slot"].state = "finishing"
        future = self.executor.submit(
            verify_output,
            task["output_root"],
            task["final_dir"],
            task["id"],
            task["attempt_id"],
            attempt["commit_token"],
        )
        self.verifications.append((task, future, attempt, recovering))

    def _release(self, slot):
        entry = self.running.get(slot.task_id)
        if not entry or not entry["terminal"] or entry["verifying"]:
            return
        if slot.process and (slot.retiring or not entry["idle"]):
            return
        task = self.store.get(slot.task_id)
        if task["state"] == "cancelling":
            self.store.transition(task["id"], entry["attempt_id"], "cancelled")
            task = self.store.get(task["id"])
        self.store.schedule_cleanup(
            entry["attempt_id"], delay_days=0 if task["state"] in {"completed", "cancelled", "ready"} else 7
        )
        self.running.pop(slot.task_id, None)
        slot.task_id = None
        slot.state = "idle" if slot.process and not slot.retiring else "stopped"
        if task["state"] in {"ready", "completed"}:
            slot.failures = 0
        self.changed.emit()
        self.dispatch()

    def _retire(self, slot):
        slot.retiring, slot.state = True, "retiring"
        if slot.job:
            slot.job.close()
            slot.job = None
        if slot.process:
            slot.process.kill()

    def _fault(self, slot, code):
        entry = self.running.get(slot.task_id)
        if entry:
            task = self.store.get(slot.task_id)
            if task["state"] != "finalizing" and task["state"] != "cancelling":
                self.store.transition(
                    task["id"],
                    entry["attempt_id"],
                    "interrupted",
                    error="内核通信中断，可重新下载。",
                    error_code=code,
                )
                entry["terminal"] = True
        slot.failures += 1
        self._retire(slot)
        if self.switching:
            self.switching = False
            self.engine_switch_failed.emit(code)

    def _process_error(self, slot, process, error):
        if slot.process is process and error == QProcess.ProcessError.FailedToStart:
            self._exited(slot, process)

    def _exited(self, slot, process):
        if slot.process is not process:
            return
        was_retiring = slot.retiring
        slot.retiring = True
        self._read(slot, process)
        if slot.job:
            slot.job.close()
        slot.job, slot.process = None, None
        if not was_retiring:
            slot.failures += 1
        slot.restart_after = time.monotonic() + min(4, 0.25 * 2 ** min(slot.failures, 4))
        entry = self.running.get(slot.task_id)
        if entry:
            task = self.store.get(slot.task_id)
            if task["state"] == "finalizing":
                self._verify(task)
            elif task["state"] != "cancelling" and not entry["terminal"]:
                self.store.transition(
                    task["id"],
                    entry["attempt_id"],
                    "interrupted",
                    error="内核意外退出，可重新下载。",
                    error_code="WORKER_CRASHED",
                )
            entry["terminal"], entry["idle"] = True, True
            self._release(slot)
        else:
            slot.state = "stopped"
        process.deleteLater()
        if self.switching and not was_retiring:
            self.switching = False
            self.engine_switch_failed.emit("ENGINE_START_FAILED")
        self.changed.emit()

    def cancel(self, task_id):
        task = self.store.get(task_id)
        if not task:
            return
        if task["state"] == "ready":
            self.store.transition(task_id, task["attempt_id"], "cancelled")
            self.changed.emit()
            return
        if task_id not in self.running:
            if task["state"] in {"queued", "ready"}:
                self.store.transition(task_id, task["attempt_id"], "cancelled")
                self.changed.emit()
            return
        if not self.store.transition(task_id, task["attempt_id"], "cancelling"):
            return
        entry = self.running[task_id]
        entry["cancel_deadline"] = time.monotonic() + self.cancel_grace
        self._send(entry["slot"], {"type": "cancel", "task_id": task_id, "attempt_id": entry["attempt_id"]})
        self.changed.emit()

    def _tick(self):
        if self.history_audit is not None and self.history_audit.done():
            for task_id, attempt_id, revision in self.history_audit.result():
                with self.store.transaction():
                    self.store.db.execute(
                        """UPDATE tasks SET state='failed',error_code='INVALID_SAVED_MEDIA',
                        error='已保存文件是播放列表或错误网页，请重新下载。',revision=revision+1
                        WHERE id=? AND attempt_id=? AND revision=? AND state='completed'""",
                        (task_id, attempt_id, revision),
                    )
            self.history_audit = None
            self.changed.emit()
        if self.switch_pending is not None and not any(s.process for s in self.slots) and not self.closing:
            self.engine, self.switch_pending = self.switch_pending, None
            for slot in self.slots:
                slot.failures, slot.restart_after, slot.retiring = 0, 0, False
            self.switching = True
            self._spawn(self.slots[0])
        clock = time.monotonic()
        for slot in self.slots:
            if slot.process and not slot.retiring:
                limit = self.startup_timeout if slot.state == "starting" else self.heartbeat_timeout
                if clock - slot.last_seen > limit:
                    self._fault(slot, "WORKER_TIMEOUT")
            entry = self.running.get(slot.task_id)
            if entry and entry["cancel_deadline"] and clock >= entry["cancel_deadline"]:
                self._retire(slot)
        for item in list(self.verifications):
            task, future, attempt, recovering = item
            if not future.done():
                continue
            try:
                manifest = future.result()
                self.store.complete(task["id"], task["attempt_id"], manifest)
            except Exception:
                self.store.transition(
                    task["id"],
                    task["attempt_id"],
                    "interrupted",
                    error="文件提交状态未能确认，请检查结果后重新下载。",
                    error_code="COMMIT_UNCONFIRMED",
                )
            self.verifications.remove(item)
            entry = self.running.get(task["id"])
            if entry and entry["attempt_id"] == task["attempt_id"]:
                entry["verifying"], entry["terminal"] = False, True
                self._release(entry["slot"])
            else:
                current = self.store.get(task["id"])
                self.store.schedule_cleanup(
                    task["attempt_id"], delay_days=0 if current["state"] == "completed" else 7
                )
            self.changed.emit()
        for attempt_id, future in list(self.cleanups.items()):
            if future.done():
                try:
                    success = future.result()
                except Exception:
                    success = False
                self.store.finish_cleanup(attempt_id, success)
                self.cleanups.pop(attempt_id)
        for task_id in list(self.pending_removals):
            if task_id not in self.running and self.store.remove_history(task_id):
                self.pending_removals.remove(task_id)
                self.progress.pop(task_id, None)
                self.changed.emit()
        if not self.closing:
            for item in self.store.cleanup_due():
                if item["attempt_id"] not in self.cleanups and not any(
                    e["attempt_id"] == item["attempt_id"] for e in self.running.values()
                ):
                    self.cleanups[item["attempt_id"]] = self.executor.submit(
                        cleanup_work_directory, item["output_root"], item["task_id"], item["attempt_id"]
                    )
            self.dispatch()

    def remove_history(self, task_id):
        task = self.store.get(task_id)
        if (
            not task
            or task_id in self.running
            or task["state"] not in {"completed", "failed", "cancelled", "interrupted"}
        ):
            return False
        self.store.request_history_cleanup(task_id)
        self.pending_removals.add(task_id)
        self.changed.emit()
        return True

    def switch_engine(self, engine):
        if (
            self.running
            or self.verifications
            or self.switch_pending is not None
            or self.switching
            or self.closing
        ):
            raise RuntimeError("Engine switch requires idle workers")
        self.dispatch_paused = True
        self.switch_pending = engine
        for slot in self.slots:
            if slot.process:
                self._retire(slot)

    def resume_dispatch(self):
        self.dispatch_paused = False
        self.dispatch()

    def shutdown(self):
        self.closing = True
        for task_id in list(self.running):
            self.cancel(task_id)
        for slot in self.slots:
            if slot.process and slot.task_id is None:
                self._send(slot, {"type": "shutdown"})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(slot.process for slot in self.slots):
            QCoreApplication.processEvents()
            self._tick()
            for slot in self.slots:
                if slot.process and slot.task_id is None:
                    self._send(slot, {"type": "shutdown"})
            time.sleep(0.01)
        for slot in self.slots:
            if slot.process:
                process = slot.process
                self._retire(slot)
                process.waitForFinished(1000)
        self.timer.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
