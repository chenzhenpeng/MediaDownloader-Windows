"""Download independent updates, then probe and activate one complete combination."""

from __future__ import annotations

import shutil
import time
import uuid

from packaging.version import Version

from .component_catalog import newer
from .update_archive import no_reparse
from .update_contracts import UpdateError
from .update_manager import UpdateManager
from .update_store import update_lock


class ProfileUpdateManager(UpdateManager):
    def check(self, component="engine"):
        if component not in {"all", "engine", "parsehub", "worker", "python-runtime", "media-tools"}:
            raise ValueError("Unknown component target")
        if self.busy or self.closing:
            return
        self.target, self.manifest, self.official_wheel = component, None, None
        self.release_plan = []
        self.cancelled.clear()
        self.job = "check"
        self.service.store.set_setting("update_last_check", time.time())
        self._set(
            "checking",
            "正在检查 ParseHub 官方版本…"
            if component == "parsehub"
            else "正在检查 Worker、Python 环境和媒体工具…",
        )
        current = self.service.engine

        def run():
            if component == "parsehub":
                from .official_install import runtime_contract
                from .official_packages import check_latest

                wheel = check_latest(cancelled=self.cancelled.is_set)
                runtime_contract(current)
                if Version(wheel.version) <= Version(current.parser_version):
                    return None
                self.official_wheel = wheel
                return (
                    {
                        "component": "parsehub",
                        "engine_version": wheel.version,
                        "parsehub_version": wheel.version,
                        "size_bytes": wheel.size,
                        "official": True,
                    },
                    b"",
                    b"",
                )
            if not self.engines.trust.configured:
                raise UpdateError("UPDATE_SOURCE", "尚未配置独立组件更新源。")
            raw, signature = self.feed.check(cancelled=self.cancelled.is_set)
            releases = self.engines.accept_catalog(raw, signature)
            latest = {}
            for manifest, body, signed in releases:
                kind = manifest.get("component")
                if kind == "media-tools" and self.engines.refs()["media-tools"].startswith(
                    "media-tools-local-"
                ):
                    continue  # Explicit local tools are never replaced by managed updates.
                if (
                    kind not in {"worker", "python-runtime", "media-tools"}
                    or component not in {"all", "engine", kind}
                    or not newer(manifest, current)
                ):
                    continue
                if kind not in latest or Version(manifest["engine_version"]) > Version(
                    latest[kind][0]["engine_version"]
                ):
                    latest[kind] = manifest, body, signed
            if not latest:
                return None
            self.release_plan = [latest[kind] for kind in sorted(latest)]
            for _, body, signed in self.release_plan:
                self.engines.accept(body, signed)
            plan = {
                "component": "environment-plan",
                "components": [m for m, _, _ in self.release_plan],
                "engine_version": ", ".join(
                    m["component"] + " " + m["engine_version"] for m, _, _ in self.release_plan
                ),
                "size_bytes": sum(m["size_bytes"] for m, _, _ in self.release_plan),
            }
            return plan, b"", b""

        self.future = self.executor.submit(run)

    def configure_tools(self, directory=None):
        if self.busy or self.closing:
            return
        if self.service.store.setting("engine_update_locked", False):
            self._set("idle", "执行组合已锁定，请先取消锁定。")
            return
        self.cancelled.clear()
        self.job = "configure-tools"
        self.target = "engine"
        self._set("checking", "正在验证媒体工具和完整执行组合…")
        self.future = self.executor.submit(
            lambda: self.engines.configure_tools(directory, cancelled=self.cancelled.is_set)
        )

    def install(self):
        if self.busy or self.closing or self.manifest is None:
            return
        if self.service.store.setting("engine_update_locked", False):
            self._set("idle", "执行组合已锁定，请先取消锁定。")
            return
        if not newer(self.manifest, self.service.engine):
            self._set("idle", "没有需要升级的组件。")
            return
        self.cancelled.clear()
        self.progress = 0, self.manifest["size_bytes"]
        self.job = "install"
        self._set("downloading", "正在下载变化的组件；完整验证后统一切换…")

        def run():
            with update_lock(self.engines.root, name="update-session.lock"):
                with update_lock(self.engines.root):
                    self.engines.discard_staging()
                directory = self.engines.root / "updates/downloads"
                no_reparse(directory)
                directory.mkdir(parents=True, exist_ok=True)
                if self.manifest.get("official"):
                    from .official_packages import download_wheel

                    archive = directory / (uuid.uuid4().hex + ".whl")
                    try:
                        download_wheel(
                            self.official_wheel,
                            archive,
                            cancelled=self.cancelled.is_set,
                            progress=self._progress,
                        )
                        return self.engines.install_official(
                            self.official_wheel, archive, cancelled=self.cancelled.is_set
                        )
                    finally:
                        archive.unlink(missing_ok=True)
                budget = sum(m["size_bytes"] + m["unpacked_size_bytes"] for m, _, _ in self.release_plan)
                if shutil.disk_usage(self.engines.root).free < budget + 100 * 1024**2:
                    raise UpdateError("UPDATE_DISK", "磁盘空间不足。")
                refs, completed = self.engines.refs(), 0
                for manifest, raw, signature in self.release_plan:
                    if self.cancelled.is_set():
                        raise UpdateError("UPDATE_CANCELLED", "更新已取消。")
                    base = completed
                    archive = self.feed.download(
                        manifest,
                        directory,
                        cancelled=self.cancelled.is_set,
                        progress=lambda done, total, base=base: self._progress(
                            base + done, self.manifest["size_bytes"]
                        ),
                    )
                    try:
                        refs[manifest["component"]] = self.engines.stage_component(
                            archive, raw, signature, cancelled=self.cancelled.is_set
                        )
                    finally:
                        archive.unlink(missing_ok=True)
                    completed += manifest["size_bytes"]
                return self.engines.prepare(refs, cancelled=self.cancelled.is_set)

        self.future = self.executor.submit(run)
