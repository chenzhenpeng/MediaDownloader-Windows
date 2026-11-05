"""Private stdio bridge between the native Windows shell and existing task services.

Requests never go on command lines. Snapshots contain only display data and
credential-presence flags. Cookies are returned only by an explicit per-platform
private read request for the native masked password control, never in snapshots.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QCoreApplication, QLockFile, QStandardPaths, QTimer

from . import __version__
from .engine import resolve_engine
from .engine_server import stdin_chunks
from .official_update import check_official_release
from .platforms import PLATFORMS
from .presentation import TERMINAL, diagnostic_report, media_description, preview_data, progress_text
from .repository import Store
from .scheduler import TaskService
from .storage import data_directory, extract_links
from .ui_capabilities import CapabilityReader
from .update_contracts import Trust, UpdateError, load_trust
from .update_manager import UpdateManager, default_trust_file
from .update_store import EngineStore
from .windows import protect, unprotect

WIRE = sys.stdout


class DesktopHost:
    def __init__(self, app, store, service, engines):
        self.app, self.store, self.service = app, store, service
        self.updates = UpdateManager(service, engines)
        self.inbox = queue.Queue()
        self.available = set()
        self.view = {"scope": "active", "query": "", "state": "", "offset": 0}
        self.pending_snapshot = True
        self.sequence = 0
        self.closing = False
        self.official_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="official-release")
        self.official_future = None
        self.official_result = {
            "status": "idle",
            "message": "可检查 ParseHub 官方版本；内核安装仍需兼容更新包。",
        }
        self.detail_id = ""
        self.submitted_ids = set()
        self.sent_thumbnails = {}
        self.visible_thumbnails = set()
        self.reader = CapabilityReader()
        self.reader.changed.connect(self.capabilities_changed)
        service.engine_activated.connect(self.reader.refresh)
        service.changed.connect(self.changed)
        self.updates.changed.connect(self.changed)
        self.reader.refresh(service.engine)
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        threading.Thread(target=self.receive, daemon=True, name="native-requests").start()

    def emit(self, kind, **payload):
        self.sequence += 1
        WIRE.write(
            json.dumps({"bridge": 1, "event": kind, "sequence": self.sequence, **payload}, ensure_ascii=False)
            + "\n"
        )
        WIRE.flush()

    def changed(self):
        self.pending_snapshot = True

    def capabilities_changed(self, rows):
        self.available = {name for name, _ in rows or []}
        self.changed()

    def receive(self):
        buffer = b""
        try:
            for chunk in stdin_chunks():
                buffer += chunk
                if len(buffer) > 1024 * 1024:
                    raise ValueError("Oversized request")
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self.inbox.put(json.loads(line))
        except (ValueError, OSError):
            pass
        finally:
            self.inbox.put({"method": "shutdown", "id": 0})

    def tick(self):
        if self.official_future is not None and self.official_future.done():
            try:
                self.official_result = self.official_future.result()
            except Exception:
                self.official_result = {"status": "error", "message": "检查官方源失败，请稍后重试。"}
            self.official_future = None
            self.changed()
        for _ in range(20):
            try:
                request = self.inbox.get_nowait()
            except queue.Empty:
                break
            try:
                result = self.handle(request["method"], request.get("params") or {})
                self.emit("response", id=request.get("id"), result=result)
            except Exception as exc:
                # Never forward exception strings from a request containing credentials.
                message = getattr(exc, "message", None) or "操作未完成，请检查输入后重试。"
                self.emit("response", id=request.get("id"), error={"message": message})
            if self.closing:
                return
        if self.pending_snapshot:
            self.pending_snapshot = False
            self.emit("snapshot", data=self.snapshot())

    def public_task(self, task, stats):
        preview = preview_data(task)
        media = preview.get("media") or []
        invalid = task["error_code"] == "INVALID_SAVED_MEDIA"
        state = task["state"]
        progress = self.service.progress.get(task["id"], {})
        size, ended = stats.get(task["attempt_id"], (None, None))
        thumbnail = (preview.get("thumbnails") or [""])[0]
        changed_thumbnail = thumbnail if self.sent_thumbnails.get(task["id"]) != thumbnail else None
        self.sent_thumbnails[task["id"]] = thumbnail
        self.visible_thumbnails.add(task["id"])
        return {
            "id": task["id"],
            "title": task["title"] or "正在获取作品信息",
            "state": state,
            "action": task["action"],
            "has_preview": bool(preview.get("resource_id")),
            "platform": task["platform"],
            "platform_name": PLATFORMS[task["platform"]].name
            if task["platform"] in PLATFORMS
            else "未知平台",
            "error": task["error"],
            "error_code": task["error_code"],
            "invalid": invalid,
            "media": [media_description(item) for item in media[:5]],
            "thumbnail": changed_thumbnail,
            "path": task["final_dir"] or task["output_root"],
            "size": size,
            "ended_at": ended,
            "progress": progress_text(progress) if state == "downloading" else "",
            "percent": progress.get("percent"),
            "busy": task["id"] in self.service.running,
        }

    def snapshot(self):
        tasks = [
            dict(row)
            for row in self.store.db.execute(
                "SELECT id,title,platform,state,attempt_id,created_at FROM tasks "
                "ORDER BY created_at DESC,id DESC"
            )
        ]
        self.visible_thumbnails = set()
        stats = {
            r[0]: (r[1], r[2])
            for r in self.store.db.execute(
                """SELECT a.id,SUM(o.size_bytes),a.finished_at FROM attempts a
            LEFT JOIN outputs o ON o.attempt_id=a.id GROUP BY a.id"""
            )
        }
        selected = []
        query = str(self.view["query"]).casefold()
        for task in tasks:
            scope, state = self.view["scope"], task["state"]
            if scope == "active" and state in TERMINAL or scope == "history" and state not in TERMINAL:
                continue
            state_filter = self.view["state"]
            if state_filter == "active" and state in TERMINAL:
                continue
            if state_filter and state_filter != "active" and state != state_filter:
                continue
            platform_name = PLATFORMS[task["platform"]].name if task["platform"] in PLATFORMS else "未知平台"
            if query and query not in f"{task['title']} {platform_name}".casefold():
                continue
            selected.append(task)
        offset = self.view["offset"]

        def public(t):
            return self.public_task(self.store.get(t["id"]), stats)

        update_state = self.updates.engines.state()
        result = {
            "client_version": __version__,
            "engine_version": self.service.engine.version,
            "runtime_version": getattr(self.service.engine, "runtime_version", "")
            or self.service.engine.version,
            "parser_version": getattr(self.service.engine, "parser_version", ""),
            "parser_component_version": getattr(self.service.engine, "parser_component_version", "")
            or self.service.engine.version,
            "counts": {
                "active": sum(t["state"] not in TERMINAL for t in tasks),
                "history": sum(t["state"] in TERMINAL for t in tasks),
                "completed": sum(t["state"] == "completed" for t in tasks),
            },
            "tasks": [public(t) for t in selected[offset : offset + 50]],
            "detail": next((public(t) for t in tasks if t["id"] == self.detail_id), None),
            "submitted": [public(t) for t in tasks if t["id"] in self.submitted_ids],
            "total": len(selected),
            "offset": offset,
            "ready": [public(t) for t in [t for t in tasks if t["state"] == "ready"][:10]],
            "recent": [public(t) for t in [t for t in tasks if t["state"] == "completed"][:3]],
            "settings": {
                "output_root": self.store.setting(
                    "output_root",
                    QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation),
                ),
                "theme": self.store.setting("theme", "system"),
                "max_workers": self.store.setting("max_workers", 2),
            },
            "platforms": [
                {
                    "id": key,
                    "name": spec.name,
                    "types": spec.media_types,
                    "available": spec.name in self.available,
                    "hint": spec.credential_hint,
                    "cookie_saved": bool(self.store.setting(f"{key}.cookie")),
                    "proxy_saved": bool(self.store.setting(f"{key}.proxy")),
                }
                for key, spec in PLATFORMS.items()
            ],
            "update": {
                "official": getattr(
                    self, "official_result", {"status": "idle", "message": "可检查官方版本。"}
                ),
                "status": self.updates.status,
                "component": (getattr(self.updates, "manifest", None) or {}).get("component", "engine"),
                "candidate_version": (getattr(self.updates, "manifest", None) or {}).get(
                    "engine_version", ""
                ),
                "message": self.updates.message,
                "configured": self.updates.engines.trust.configured,
                "busy": self.updates.busy,
                "downloaded_bytes": getattr(self.updates, "progress", (0, 0))[0],
                "total_bytes": getattr(self.updates, "progress", (0, 0))[1],
                "cancel_requested": bool(
                    self.updates.busy
                    and getattr(self.updates, "cancelled", None)
                    and self.updates.cancelled.is_set()
                ),
                "locked": self.store.setting("engine_update_locked", False),
                "auto": self.store.setting("update_auto_check", False),
                "can_rollback": update_state["current"] != update_state["last_good"],
            },
        }
        self.sent_thumbnails = {
            key: value for key, value in self.sent_thumbnails.items() if key in self.visible_thumbnails
        }
        return result

    def handle(self, method, p):
        if method == "hello":
            self.changed()
            return {"bridge": 1}
        if method == "view":
            scope = p.get("scope", "active")
            if scope not in {"active", "history", "all"}:
                raise ValueError("Invalid scope")
            self.view = {
                "scope": scope,
                "query": str(p.get("query", ""))[:500],
                "state": str(p.get("state", "")),
                "offset": max(0, int(p.get("offset", 0))),
            }
        elif method == "inspect":
            links = extract_links(str(p.get("text", ""))[:32768])
            if not links:
                raise ValueError("Unsupported input")
            root = str(
                Path(
                    p.get("output_root")
                    or self.store.setting("output_root")
                    or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
                ).resolve()
            )
            Path(root).mkdir(parents=True, exist_ok=True)
            self.store.set_setting("output_root", root)
            ids = self.service.submit(links[:50], root)
            self.submitted_ids = set(ids)
            self.changed()
            return {"ids": ids}
        elif method == "detail":
            self.detail_id = str(p.get("id", ""))
        elif method in {"download", "cancel", "remove"}:
            task = self.store.get(str(p.get("id", "")))
            if not task:
                raise ValueError("Unknown task")
            if method == "download":
                self.service.retry(task["id"])
            elif method == "cancel":
                self.service.cancel(task["id"])
            else:
                self.service.remove_history(task["id"])
        elif method == "file":
            task = self.store.get(str(p.get("id", "")))
            if not task:
                raise ValueError("Unknown task")
            path = Path(task["final_dir"] or task["output_root"])
            if p.get("media") and task["state"] == "completed":
                files = [
                    r[0]
                    for r in self.store.db.execute(
                        "SELECT relative_path FROM outputs WHERE attempt_id=? ORDER BY relative_path",
                        (task["attempt_id"],),
                    )
                ]
                media = next(
                    (
                        name
                        for name in files
                        if Path(name).suffix.lower()
                        in {
                            ".mp4",
                            ".mkv",
                            ".mov",
                            ".webm",
                            ".jpg",
                            ".jpeg",
                            ".png",
                            ".webp",
                            ".gif",
                            ".mp3",
                            ".m4a",
                        }
                    ),
                    None,
                )
                media = media or next(
                    (name for name in files if Path(name).name in {"正文.md", "正文.txt"}), None
                )
                if media:
                    candidate = path / media
                    if not candidate.resolve().is_relative_to(path.resolve()):
                        raise ValueError("Output escaped")
                    path = candidate
            if not path.exists():
                raise ValueError("Missing file")
            return {"path": str(path)}
        elif method == "settings":
            for key in {"output_root", "theme", "max_workers"} & p.keys():
                value = p[key]
                if key == "max_workers":
                    value = max(1, min(4, int(value)))
                if key == "theme" and value not in {"system", "light", "dark"}:
                    raise ValueError("Invalid theme")
                self.store.set_setting(key, value)
        elif method == "connection_read":
            platform = p["platform"]
            if platform not in PLATFORMS:
                raise ValueError("Unknown platform")
            saved = self.store.setting(f"{platform}.cookie")
            return {"cookie": unprotect(bytes.fromhex(saved)) if saved else ""}
        elif method == "connection":
            platform = p["platform"]
            if platform not in PLATFORMS:
                raise ValueError("Unknown platform")
            proxy, cookie = str(p.get("proxy", "")).strip(), str(p.get("cookie", "")).strip()
            if proxy:
                parsed = urlsplit(proxy)
                if parsed.scheme not in {"http", "https", "socks5", "socks5h"} or not parsed.hostname:
                    raise ValueError("Invalid proxy")
                self.store.set_setting(f"{platform}.proxy", protect(proxy).hex())
            if cookie:
                self.store.set_setting(f"{platform}.cookie", protect(cookie).hex())
            for key in ("cookie", "proxy"):
                if p.get(f"clear_{key}"):
                    self.store.set_setting(f"{platform}.{key}", None)
        elif method == "official_update":
            if self.official_future is None:
                self.official_result = {"status": "checking", "message": "正在检查 ParseHub 官方版本…"}
                self.official_future = self.official_executor.submit(
                    check_official_release, self.service.engine.upstream_sha
                )
        elif method == "update":
            action = p["action"]
            if action in {"check", "install", "cancel", "rollback"}:
                getattr(self.updates, action)()
            elif action == "lock":
                self.store.set_setting("engine_update_locked", bool(p["value"]))
                if p["value"]:
                    self.updates.cancel()
            elif action == "auto":
                self.store.set_setting("update_auto_check", bool(p["value"]))
        elif method == "diagnostics":
            return diagnostic_report(self.store, self.service.engine)
        elif method == "shutdown":
            self.closing = True
            self.timer.stop()
            self.reader.shutdown()
            self.updates.shutdown()
            self.official_executor.shutdown(wait=False, cancel_futures=True)
            self.service.shutdown()
            self.store.close()
            self.app.quit()
            return {}
        else:
            raise ValueError("Unknown method")
        self.changed()
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-dir", type=Path)
    args = parser.parse_args()
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    app = QCoreApplication([])
    app.setApplicationName("Media Downloader")
    lock = QLockFile(str(data_directory() / "application.lock"))
    if not lock.tryLock(0):
        WIRE.write(
            json.dumps(
                {"event": "fatal", "message": "应用已在运行，请先关闭已打开的客户端。"}, ensure_ascii=False
            )
            + "\n"
        )
        WIRE.flush()
        return 1
    bundled = resolve_engine(args.engine_dir)
    try:
        trust = load_trust(default_trust_file())
    except UpdateError:
        trust = Trust("stable", {})
    engines = EngineStore(data_directory(), trust, bundled)
    store = Store(data_directory() / "tasks.sqlite3")
    service = TaskService(store, engine=engines.recover())
    host = DesktopHost(app, store, service, engines)
    app.aboutToQuit.connect(lambda: None if host.closing else host.handle("shutdown", {}))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
