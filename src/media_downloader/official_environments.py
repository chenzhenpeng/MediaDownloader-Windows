"""Transactional selection of locally prepared official-package environments.

Experimental: acquisition/authentication and worker launch are deliberately not
provided here. Callers must authenticate packages before preparing an environment.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .official_paths import candidate_python
from .update_archive import no_reparse


class OfficialEnvironments:
    def __init__(self, root: Path):
        self.root = root.absolute()
        no_reparse(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "selection.sqlite3"
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS environments (
                    id TEXT PRIMARY KEY, version TEXT NOT NULL,
                    wheel_hash TEXT NOT NULL, inventory TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS selection (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    active TEXT, previous TEXT, generation INTEGER NOT NULL);
                INSERT OR IGNORE INTO selection VALUES (1, NULL, NULL, 0);
                CREATE TABLE IF NOT EXISTS quarantined (
                    environment TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS launches (
                    token TEXT PRIMARY KEY, environment TEXT NOT NULL,
                    generation INTEGER NOT NULL, state TEXT NOT NULL);
            """)

    @contextmanager
    def _connect(self):
        no_reparse(self.database)
        db = sqlite3.connect(self.database, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def directory(self, identifier: str) -> Path:
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", identifier):
            raise ValueError("Invalid environment identifier")
        path = self.root / "environments" / identifier
        no_reparse(path)
        return path

    def _inventory(self, identifier):
        directory = self.directory(identifier)
        candidate_python(directory)
        inventory = {}
        # Bytecode is also inventoried: callers must disable writes while probing
        # and running a selected environment.
        for path in sorted(directory.rglob("*")):
            no_reparse(path)
            if path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                inventory[path.relative_to(directory).as_posix()] = digest.hexdigest()
        return json.dumps(inventory, sort_keys=True)

    def validate(self, identifier, *, version, wheel_hash, probe, expected_inventory=None):
        """Record a candidate only after a caller-owned bounded probe succeeds."""
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version):
            raise ValueError("Invalid official version")
        if not isinstance(wheel_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", wheel_hash):
            raise ValueError("Invalid wheel digest")
        before = self._inventory(identifier)
        if expected_inventory is not None and json.loads(before) != expected_inventory:
            raise ValueError("Candidate differs from expected inventory before probe")
        report = probe(self.directory(identifier))
        required = (
            "client_preview_conversion",
            "local_transfer_bytes_verified",
            "progress_callback_received",
        )
        origin = Path(report.get("package_origin", "")).absolute()
        if (
            report.get("version") != version
            or report.get("wheel_sha256") != wheel_hash
            or not origin.is_relative_to(self.directory(identifier))
            or not all(report.get(key) is True for key in required)
        ):
            raise ValueError("Candidate compatibility probe failed")
        if self._inventory(identifier) != before:
            raise ValueError("Candidate changed during validation")
        with self._connect() as db:
            # Never rewrite the record for an existing environment identifier.
            db.execute(
                "INSERT INTO environments VALUES (?, ?, ?, ?)", (identifier, version, wheel_hash, before)
            )

    def snapshot(self):
        with self._connect() as db:
            active, previous, generation = db.execute(
                "SELECT active, previous, generation FROM selection WHERE singleton=1"
            ).fetchone()
        return {"active": active, "previous": previous, "generation": generation}

    def version(self, identifier):
        self.directory(identifier)
        with self._connect() as db:
            row = db.execute("SELECT version FROM environments WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("Unknown official environment")
        return row[0]

    def _verify(self, db, identifier):
        if db.execute("SELECT 1 FROM quarantined WHERE environment=?", (identifier,)).fetchone():
            raise ValueError("Candidate failed startup and is quarantined")
        row = db.execute("SELECT inventory FROM environments WHERE id=?", (identifier,)).fetchone()
        if row is None or self._inventory(identifier) != row[0]:
            raise ValueError("Candidate is unvalidated or has changed")

    def select(self, identifier, *, expected_generation):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active, _, generation = db.execute(
                "SELECT active, previous, generation FROM selection WHERE singleton=1"
            ).fetchone()
            if generation != expected_generation:
                raise ValueError("Environment selection changed; refresh before retrying")
            self._verify(db, identifier)
            if identifier != active:
                db.execute(
                    "UPDATE selection SET active=?, previous=?, generation=generation+1 WHERE singleton=1",
                    (identifier, active),
                )
        return self.snapshot()

    def rollback(self, *, expected_generation):
        state = self.snapshot()
        if state["previous"] is None:
            raise ValueError("No previous official environment")
        return self.select(state["previous"], expected_generation=expected_generation)

    def resolve(self):
        """Resolve for a new task; an existing task keeps its prior path."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT active FROM selection WHERE singleton=1").fetchone()[0]
            if active is None:
                return None
            self._verify(db, active)
            return self.directory(active)

    def reserve_launch(self):
        """Pin a new launch to a verified environment and selection generation."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active, generation = db.execute(
                "SELECT active, generation FROM selection WHERE singleton=1"
            ).fetchone()
            if active is None:
                return None
            self._verify(db, active)
            token = uuid.uuid4().hex
            db.execute("INSERT INTO launches VALUES (?, ?, ?, 'starting')", (token, active, generation))
        return {"token": token, "environment": active, "directory": self.directory(active)}

    def launch_ready(self, token):
        """Call only after the bounded worker startup handshake succeeds."""
        with self._connect() as db:
            updated = db.execute(
                "UPDATE launches SET state='ready' WHERE token=? AND state='starting'", (token,)
            ).rowcount
            if updated != 1:
                raise ValueError("Launch is unknown or no longer starting")

    def finish_launch(self, token, *, startup_failed=False):
        """A platform/download failure after readiness must never trigger rollback.

        The supervisor also uses startup_failed for a timeout or a known abandoned
        startup. It must not infer abandonment simply from restarting the UI.
        """
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            launch = db.execute(
                "SELECT environment, generation, state FROM launches WHERE token=?", (token,)
            ).fetchone()
            if launch is None or launch[2] == "finished":
                raise ValueError("Launch is unknown or already finished")
            identifier, generation, state = launch
            db.execute("UPDATE launches SET state='finished' WHERE token=?", (token,))
            if not startup_failed or state != "starting":
                return False
            db.execute("INSERT OR IGNORE INTO quarantined VALUES (?)", (identifier,))
            active, previous, current_generation = db.execute(
                "SELECT active, previous, generation FROM selection WHERE singleton=1"
            ).fetchone()
            if active != identifier:
                return False
            # A delayed failure may quarantine an environment, but must not
            # overwrite a later explicit selection of that same environment.
            if current_generation != generation:
                return False
            try:
                if previous is not None:
                    self._verify(db, previous)
            except (ValueError, OSError):
                previous = None
            db.execute(
                "UPDATE selection SET active=?, previous=NULL, generation=generation+1 WHERE singleton=1",
                (previous,),
            )
            return previous is not None
