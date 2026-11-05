from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from .contracts import platform_for_url

SCHEMA = 4
TERMINAL = {"ready", "completed", "failed", "cancelled", "interrupted"}
TRANSITIONS = {
    "queued": {"parsing", "cancelled", "failed"},
    "parsing": {"ready", "downloading", "cancelling", "failed", "interrupted"},
    "downloading": {"finalizing", "cancelling", "failed", "interrupted"},
    "finalizing": {"completed", "failed", "interrupted"},
    "cancelling": {"cancelled"},
    "ready": {"cancelled"},
}


def now():
    return datetime.now(UTC).isoformat()


def source_key(source, output_root):
    url = urlsplit(source)
    query = urlencode(sorted((k, v) for k, v in parse_qsl(url.query) if k in {"p", "modal_id"}))
    value = f"{url.hostname}:{url.path.rstrip('/')}?{query}:{str(Path(output_root).resolve()).casefold()}"
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    @contextmanager
    def transaction(self):
        owner = not self.db.in_transaction
        if owner:
            self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            if owner:
                self.db.rollback()
            raise
        else:
            if owner:
                self.db.commit()

    def __init__(self, path: Path):
        self.path = Path(path)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        existing = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        if version not in {0, SCHEMA} or version == 0 and existing:
            self.db.close()
            raise RuntimeError("不支持此数据库版本，请使用当前客户端的新数据目录。")
        self.db.execute("PRAGMA journal_mode=WAL")
        with self.transaction():
            self.db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self.db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, source BLOB NOT NULL,
                title TEXT NOT NULL DEFAULT '', platform TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
                action TEXT NOT NULL, output_root TEXT NOT NULL, final_dir TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '', preview TEXT NOT NULL DEFAULT '{}',
                engine_version TEXT NOT NULL,
                upstream_sha TEXT NOT NULL, created_at TEXT NOT NULL,
                error_code TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0,
                source_key TEXT NOT NULL DEFAULT '')""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), action TEXT NOT NULL,
                state TEXT NOT NULL, queued_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                worker_pid INTEGER, engine_version TEXT NOT NULL, upstream_sha TEXT NOT NULL,
                config_snapshot TEXT NOT NULL DEFAULT '{}', work_dir TEXT NOT NULL DEFAULT '',
                final_dir TEXT NOT NULL DEFAULT '', commit_token TEXT NOT NULL DEFAULT '',
                error_code TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '')""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS outputs (
                attempt_id TEXT NOT NULL REFERENCES attempts(id), relative_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, sha256 TEXT, PRIMARY KEY(attempt_id, relative_path))""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS cleanup (
                attempt_id TEXT PRIMARY KEY REFERENCES attempts(id), due_at TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', last_error TEXT NOT NULL DEFAULT '')""")
            self.db.execute("CREATE INDEX IF NOT EXISTS tasks_queue ON tasks(state,created_at)")
            self.db.execute("CREATE INDEX IF NOT EXISTS tasks_source ON tasks(source_key,state)")
            self.db.execute("CREATE INDEX IF NOT EXISTS attempts_task ON attempts(task_id,queued_at)")
            self.db.execute("CREATE INDEX IF NOT EXISTS cleanup_pending ON cleanup(state,due_at)")
            self.db.execute(f"PRAGMA user_version={SCHEMA}")
        # Queued work survives restart. In-flight work never silently retries.
        for task in self.tasks():
            if task["state"] in {"parsing", "downloading"}:
                self.transition(
                    task["id"],
                    task["attempt_id"],
                    "interrupted",
                    error="应用上次运行被中断，可重新下载。",
                    error_code="APP_INTERRUPTED",
                )
            elif task["state"] == "cancelling":
                self.transition(task["id"], task["attempt_id"], "cancelled")

    def setting(self, key, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.transaction():
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def create(self, source, output_root, action="inspect", *, deduplicate=False):
        from . import ENGINE_VERSION, UPSTREAM_SHA
        from .windows import protect

        key = source_key(source, output_root)
        if deduplicate:
            existing = self.db.execute(
                """SELECT id FROM tasks WHERE source_key=?
                AND state IN ('queued','parsing','ready','downloading','finalizing','cancelling') LIMIT 1""",
                (key,),
            ).fetchone()
            if existing:
                return existing[0]
        task_id, attempt_id, timestamp = uuid.uuid4().hex, uuid.uuid4().hex, now()
        with self.transaction():
            self.db.execute(
                """INSERT INTO tasks
                (id,attempt_id,source,state,action,output_root,engine_version,upstream_sha,created_at,source_key,platform)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    attempt_id,
                    protect(source),
                    "queued",
                    action,
                    str(Path(output_root).resolve()),
                    ENGINE_VERSION,
                    UPSTREAM_SHA,
                    timestamp,
                    key,
                    platform_for_url(source) or "",
                ),
            )
            self.db.execute(
                """INSERT INTO attempts (id,task_id,action,state,queued_at,engine_version,upstream_sha)
                VALUES (?,?,?,?,?,?,?)""",
                (attempt_id, task_id, action, "queued", timestamp, ENGINE_VERSION, UPSTREAM_SHA),
            )
        return task_id

    def get(self, task_id):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def tasks(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM tasks ORDER BY created_at DESC,id DESC")]

    def queued(self):
        return [
            dict(r)
            for r in self.db.execute("SELECT * FROM tasks WHERE state='queued' ORDER BY created_at,id")
        ]

    def attempt(self, attempt_id):
        row = self.db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        return dict(row) if row else None

    def attempts(self, task_id):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM attempts WHERE task_id=? ORDER BY queued_at,id", (task_id,)
            )
        ]

    def update(self, task_id, **values):
        allowed = {
            "state",
            "action",
            "title",
            "platform",
            "final_dir",
            "error",
            "preview",
            "engine_version",
            "upstream_sha",
            "error_code",
        }
        if not values or not values.keys() <= allowed:
            raise ValueError("Invalid task update")
        with self.transaction():
            assignments = ",".join(f"{name}=?" for name in values)
            self.db.execute(
                f"UPDATE tasks SET {assignments},revision=revision+1 WHERE id=?", (*values.values(), task_id)
            )
            if "state" in values:
                task = self.get(task_id)
                self.db.execute(
                    "UPDATE attempts SET state=?,finished_at=? WHERE id=?",
                    (values["state"], now() if values["state"] in TERMINAL else None, task["attempt_id"]),
                )

    def transition(self, task_id, attempt_id, state, *, expected_revision=None, **values):
        with self.transaction():
            task = self.get(task_id)
            if (
                not task
                or task["attempt_id"] != attempt_id
                or state not in TRANSITIONS.get(task["state"], set())
                or expected_revision is not None
                and task["revision"] != expected_revision
            ):
                return False
            allowed = {"error", "error_code", "final_dir"}
            if not values.keys() <= allowed:
                raise ValueError("Invalid transition fields")
            fields = {"state": state, **values}
            assignments = ",".join(f"{name}=?" for name in fields)
            cursor = self.db.execute(
                f"UPDATE tasks SET {assignments},revision=revision+1 WHERE id=? AND revision=?",
                (*fields.values(), task_id, task["revision"]),
            )
            if not cursor.rowcount:
                return False
            # Cancelling a waiting preview does not rewrite its successful inspect history.
            if task["state"] != "ready":
                self.db.execute(
                    f"UPDATE attempts SET {assignments},finished_at=? WHERE id=?",
                    (*fields.values(), now() if state in TERMINAL else None, attempt_id),
                )
        return True

    def start(self, task_id, engine, pid, snapshot, work_dir):
        task = self.get(task_id)
        with self.transaction():
            if not self.transition(task_id, task["attempt_id"], "parsing"):
                return False
            self.db.execute(
                "UPDATE tasks SET engine_version=?,upstream_sha=? WHERE id=?",
                (engine.version, engine.upstream_sha, task_id),
            )
            self.db.execute(
                """UPDATE attempts SET started_at=?,worker_pid=?,engine_version=?,upstream_sha=?,
                config_snapshot=?,work_dir=? WHERE id=?""",
                (
                    now(),
                    pid,
                    engine.version,
                    engine.upstream_sha,
                    json.dumps(snapshot),
                    str(work_dir),
                    task["attempt_id"],
                ),
            )
        return True

    def retry(self, task_id):
        task = self.get(task_id)
        if not task or task["state"] not in {"ready", "failed", "cancelled", "interrupted"}:
            return False
        attempt_id = uuid.uuid4().hex
        action = "download" if json.loads(task["preview"] or "{}").get("resource_id") else "inspect"
        with self.transaction():
            self.db.execute(
                """UPDATE tasks SET attempt_id=?,state='queued',action=?,error='',error_code='',
                final_dir='',revision=revision+1 WHERE id=? AND attempt_id=?""",
                (attempt_id, action, task_id, task["attempt_id"]),
            )
            self.db.execute(
                """INSERT INTO attempts (id,task_id,action,state,queued_at,engine_version,upstream_sha)
                VALUES (?,?,?,'queued',?,?,?)""",
                (attempt_id, task_id, action, now(), task["engine_version"], task["upstream_sha"]),
            )
        return True

    def authorize_commit(self, task_id, attempt_id, final_dir):
        with self.transaction():
            if not self.transition(task_id, attempt_id, "finalizing", final_dir=final_dir):
                return None
            token = uuid.uuid4().hex
            self.db.execute("UPDATE attempts SET commit_token=? WHERE id=?", (token, attempt_id))
        return token

    def complete(self, task_id, attempt_id, manifest):
        with self.transaction():
            if not self.transition(task_id, attempt_id, "completed"):
                return False
            for item in manifest["files"]:
                self.db.execute(
                    "INSERT OR REPLACE INTO outputs VALUES (?,?,?,?)",
                    (attempt_id, item["path"], item["size"], item.get("sha256")),
                )
        return True

    def schedule_cleanup(self, attempt_id, *, delay_days=0):
        with self.transaction():
            self.db.execute(
                "INSERT OR IGNORE INTO cleanup (attempt_id,due_at,state) VALUES (?,?,'pending')",
                (attempt_id, (datetime.now(UTC) + timedelta(days=delay_days)).isoformat()),
            )

    def cleanup_due(self):
        return [
            dict(row)
            for row in self.db.execute(
                """SELECT c.*,a.task_id,a.work_dir,t.output_root
            FROM cleanup c JOIN attempts a ON a.id=c.attempt_id JOIN tasks t ON t.id=a.task_id
            WHERE c.state='pending' AND c.due_at<=?""",
                (now(),),
            )
        ]

    def finish_cleanup(self, attempt_id, success):
        with self.transaction():
            self.db.execute(
                "UPDATE cleanup SET state=?,last_error=?,due_at=? WHERE attempt_id=?",
                (
                    "done" if success else "pending",
                    "" if success else "Owned directory could not be cleaned",
                    (datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
                    attempt_id,
                ),
            )

    def source(self, task_id):
        from .windows import unprotect

        return unprotect(self.get(task_id)["source"])

    def request_history_cleanup(self, task_id):
        with self.transaction():
            for attempt in self.attempts(task_id):
                if attempt["work_dir"]:
                    self.schedule_cleanup(attempt["id"])
                    self.db.execute(
                        "UPDATE cleanup SET due_at=? WHERE attempt_id=? AND state='pending'",
                        (now(), attempt["id"]),
                    )

    def remove_history(self, task_id):
        task = self.get(task_id)
        if not task or task["state"] not in {"completed", "failed", "cancelled", "interrupted"}:
            return False
        with self.transaction():
            if self.db.execute(
                """SELECT 1 FROM cleanup c JOIN attempts a ON a.id=c.attempt_id
                WHERE a.task_id=? AND c.state<>'done'""",
                (task_id,),
            ).fetchone():
                return False
            for table in ("cleanup", "outputs"):
                self.db.execute(
                    f"DELETE FROM {table} WHERE attempt_id IN (SELECT id FROM attempts WHERE task_id=?)",
                    (task_id,),
                )
            self.db.execute("DELETE FROM attempts WHERE task_id=?", (task_id,))
            self.db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        return True

    def close(self):
        self.db.close()
