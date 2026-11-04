"""UI-thread orchestration; network, hashes, unpacking and self-tests run off-thread."""

from __future__ import annotations

import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .update_contracts import UpdateError
from .update_feed import UpdateFeed
from .update_store import update_lock


def default_trust_file():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "update-trust.json"
    return Path(__file__).resolve().parents[2] / "packaging" / "update-trust.json"


class UpdateManager(QObject):
    changed = Signal()

    def __init__(self, service, engine_store, parent=None, *, feed=None):
        super().__init__(parent)
        self.service, self.engines = service, engine_store
        self.feed = feed or UpdateFeed(engine_store.trust)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="engine-update")
        self.future, self.job, self.prepared, self.manifest = None, None, None, None
        self.raw, self.signature = b"", b""
        self.cancelled = threading.Event()
        self.closing = False
        self.progress = (0, 0)
        self.status = "idle" if engine_store.trust.configured else "unconfigured"
        self.message = engine_store.recovery_message or (
            "可手动检查受信任的内核更新。" if engine_store.trust.configured else "尚未配置受信任的更新源。"
        )
        self.switch_target, self.recovering = None, False
        self._previous_engine = service.engine
        service.engine_activated.connect(self._activated)
        service.engine_switch_failed.connect(self._switch_failed)
        service.engine_unhealthy.connect(self._unhealthy)
        service.rollback_on_start_failure = engine_store.state()["current"] != "bundled"
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    @property
    def busy(self):
        return self.status in {"checking", "downloading", "waiting", "switching", "recovering"}

    def _set(self, status, message):
        self.status, self.message = status, message
        self.changed.emit()

    def check(self):
        if self.busy or self.closing or not self.engines.trust.configured:
            return
        self.cancelled.clear()
        self.job = "check"
        self.service.store.set_setting("update_last_check", time.time())
        self._set("checking", "正在检查签名更新清单…")

        def run():
            raw, signature = self.feed.check(cancelled=self.cancelled.is_set)
            manifest = self.engines.accept(raw, signature)
            return manifest, raw, signature

        self.future = self.executor.submit(run)

    def install(self):
        if self.busy or self.closing or self.manifest is None:
            return
        if self.service.store.setting("engine_update_locked", False):
            self._set("idle", "当前内核已锁定，请先取消版本锁定。")
            return
        self.cancelled.clear()
        self.progress = (0, self.manifest["size_bytes"])
        self.job = "install"
        self._set("downloading", "正在下载、校验并自检候选内核…")

        def run():
            with update_lock(self.engines.root, name="update-session.lock"):
                with update_lock(self.engines.root):
                    self.engines.discard_staging()
                budget = self.manifest["size_bytes"] + self.manifest["unpacked_size_bytes"] + 100 * 1024**2
                if shutil.disk_usage(self.engines.root).free < budget:
                    raise UpdateError("UPDATE_DISK", "磁盘空间不足，无法下载并安装此内核。")
                archive = self.feed.download(
                    self.manifest,
                    self.engines.root / "updates" / "downloads",
                    cancelled=self.cancelled.is_set,
                    progress=self._progress,
                )
                try:
                    return self.engines.install(
                        archive, self.raw, self.signature, cancelled=self.cancelled.is_set
                    )
                finally:
                    archive.unlink(missing_ok=True)
                    try:
                        with update_lock(self.engines.root):
                            self.engines.discard_staging()
                    except (OSError, UpdateError):
                        pass

        self.future = self.executor.submit(run)

    def _progress(self, done, total):
        self.progress = done, total

    def rollback(self):
        if self.busy or self.closing:
            return
        if self.service.store.setting("engine_update_locked", False):
            self._set("idle", "当前内核已锁定，请先取消版本锁定。")
            return
        self._prepare_rollback()

    def _prepare_rollback(self):
        state = self.engines.state()
        target = state["last_good"]
        if target == state["current"]:
            self._set("idle", "没有可回滚的上一版本。")
            self.service.rollback_on_start_failure = False
            self.service.resume_dispatch()
            return
        self.cancelled.clear()
        self.job = "rollback"
        self._set("checking", "正在验证上一版本内核…")

        def previous():
            try:
                return target, self.engines.installed(target)
            except (OSError, ValueError, UpdateError):
                return "bundled", self.engines.bundled

        self.future = self.executor.submit(previous)

    def _unhealthy(self):
        if not self.busy and not self.closing:
            self._prepare_rollback()

    def cancel(self):
        if self.status in {"checking", "downloading"}:
            self.cancelled.set()
            self.message = "正在取消更新操作…"
            self.changed.emit()
        elif self.status == "waiting":
            self.prepared = None
            self.service.resume_dispatch()
            self._set("idle", "已取消切换，候选内核保留供下次使用。")

    def _tick(self):
        if self.closing:
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            try:
                result = future.result()
                if self.cancelled.is_set():
                    raise UpdateError("UPDATE_CANCELLED", "更新已取消，当前内核未更改。")
                if self.job == "check":
                    self.manifest, self.raw, self.signature = result
                    if self.manifest["engine_version"] == self.service.engine.version:
                        self._set("idle", "更新源中没有不同版本的兼容内核。")
                    else:
                        self._set("available", "发现经过签名验证的兼容内核，可选择安装。")
                else:
                    self.prepared = result
                    self.service.dispatch_paused = True
                    self._set("waiting", "候选内核已验证，等待当前任务结束后切换。")
            except UpdateError as exc:
                self._set(
                    "idle" if exc.code == "UPDATE_CANCELLED" else "failed", f"{exc.message}（{exc.code}）"
                )
            except Exception as exc:
                import traceback

                self.failure_details = {
                    "type": type(exc).__name__,
                    "frames": [
                        {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                        for frame in traceback.extract_tb(exc.__traceback__)
                    ],
                }
                self._set("failed", "更新操作失败，当前内核未更改。请检查磁盘空间和文件权限。")
        if self.prepared and not self.service.running and not self.service.verifications:
            identity, engine = self.prepared
            self.prepared = None
            try:
                self._previous_engine = self.service.engine
                self.engines.begin(identity)
                self.switch_target = identity
                self.recovering = False
                self._set("switching", "正在切换内核并等待启动握手…")
                self.service.switch_engine(engine)
            except Exception:
                self._switch_failed("UPDATE_STATE")
        if self.status == "downloading":
            self.changed.emit()
        if (
            not self.busy
            and self.status in {"idle", "updated", "rolled_back"}
            and self.service.store.setting("update_auto_check", False)
            and time.time() - self.service.store.setting("update_last_check", 0) >= 86400
        ):
            self.check()

    def _activated(self, engine):
        if self.closing:
            return
        try:
            if self.recovering:
                self.engines.abort()
                self._set("rolled_back", "候选内核启动失败，已恢复之前的可用内核。")
            else:
                self.engines.confirm(self.switch_target)
                self._set(
                    "rolled_back" if self.job == "rollback" else "updated", f"当前内核：{engine.version}"
                )
            self.service.rollback_on_start_failure = self.engines.state()["current"] != "bundled"
            self.service.resume_dispatch()
            self.service.changed.emit()
            if not self.recovering:
                self.executor.submit(self.engines.prune)
        except Exception:
            self._switch_failed("UPDATE_STATE")

    def _switch_failed(self, code):
        if self.closing:
            return
        if self.recovering:
            self._set("failed", "恢复内核也无法启动，请重启应用以使用随包内核。")
            return
        self.recovering = True
        self._set("recovering", "候选内核无法启动，正在恢复上一版本…")
        try:
            # The old engine was validated before switching. Reuse it without rehashing on the UI thread.
            self.service.switch_engine(self.previous_engine)
        except (RuntimeError, AttributeError):
            self._set("failed", "内核切换失败，请重启应用恢复上一版本。")

    @property
    def previous_engine(self):
        return self._previous_engine

    def shutdown(self):
        self.closing = True
        self.cancelled.set()
        self.timer.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
