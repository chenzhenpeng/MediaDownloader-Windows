"""Authenticate original-package environments before executing candidate code.

This admits a locally assembled candidate; it is not an online downloader.
The signature authenticates metadata/inventory, not a modified ParseHub build.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.version import Version

from .official_environments import OfficialEnvironments
from .update_archive import no_reparse, safe_relative
from .update_contracts import strict_json


def verify_environment(raw, signature, trust, *, installed=False, now=None):
    if len(raw) > 8 * 1024**2 or len(signature) != 64:
        raise ValueError("Invalid environment signature envelope")
    verified_keys = set()
    for name, key in trust.keys.items():
        try:
            Ed25519PublicKey.from_public_bytes(key).verify(signature, raw)
            verified_keys.add(name)
        except (InvalidSignature, ValueError):
            pass
    if not verified_keys:
        raise ValueError("Untrusted environment signature")
    data = strict_json(raw)
    if (
        data.get("schema") != 1
        or data.get("kind") != "official-environment"
        or data.get("target") != "windows-x86_64"
        or data.get("channel") != trust.channel
        or data.get("key_id") not in verified_keys
    ):
        raise ValueError("Incompatible environment manifest")
    if type(data.get("sequence")) is not int or data["sequence"] < 1:
        raise ValueError("Invalid environment sequence")
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", data.get("version", "")):
        raise ValueError("Invalid upstream version")
    if not re.fullmatch(r"[0-9a-f]{64}", data.get("wheel_sha256", "")):
        raise ValueError("Invalid official wheel digest")
    expiry = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
    if expiry.tzinfo is None or not installed and expiry <= (now or datetime.now(UTC)):
        raise ValueError("Expired environment manifest")
    files = data.get("files")
    if not isinstance(files, dict) or not 1 <= len(files) <= 30000:
        raise ValueError("Invalid environment inventory")
    names = set()
    for name, digest in files.items():
        safe_relative(name)
        if (
            name.casefold() in names
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("Invalid inventory entry")
        names.add(name.casefold())
    return data


def verify_original_wheel(directory, wheel, manifest):
    no_reparse(wheel)
    if wheel.stat().st_size > 16 * 1024**2:
        raise ValueError("Official wheel exceeds limit")
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != manifest["wheel_sha256"]:
        raise ValueError("Official wheel digest mismatch")
    metadata_root = f"parsehub-{manifest['version']}.dist-info/"
    count, seen = 0, set()
    with zipfile.ZipFile(wheel) as archive:
        if sum(info.file_size for info in archive.infolist()) > 32 * 1024**2:
            raise ValueError("Official wheel expands beyond limit")
        for info in archive.infolist():
            name = info.filename
            safe_relative(name)
            if name.casefold() in seen:
                raise ValueError("Duplicate wheel entry")
            seen.add(name.casefold())
            # Official 2.4.0 also ships a top-level __init__.py. Verify it byte
            # for byte rather than silently dropping it or permitting any module.
            if not (name.startswith("parsehub/") or name.startswith(metadata_root) or name == "__init__.py"):
                raise ValueError("Unexpected package in official wheel")
            if info.is_dir():
                continue
            # Installers legitimately regenerate RECORD and add INSTALLER metadata.
            if name == metadata_root + "RECORD":
                continue
            installed = directory / "Lib/site-packages" / name
            no_reparse(installed)
            if not installed.is_file() or installed.read_bytes() != archive.read(info):
                raise ValueError("Official package bytes differ from original wheel")
            count += 1
    if count < 2 or "parsehub/__init__.py" not in seen or (metadata_root + "METADATA").casefold() not in seen:
        raise ValueError("Incomplete official wheel")


class VerifiedOfficialEnvironments(OfficialEnvironments):
    def __init__(self, root, trust):
        self.trust = trust
        super().__init__(root)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS authenticated (
                    environment TEXT PRIMARY KEY, manifest BLOB NOT NULL, signature BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS official_trust_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), sequence INTEGER NOT NULL);
                INSERT OR IGNORE INTO official_trust_state VALUES (1, 0);
            """)

    def _check_forward(self, db, manifest):
        highest = db.execute("SELECT sequence FROM official_trust_state WHERE singleton=1").fetchone()[0]
        if manifest["sequence"] <= highest:
            raise ValueError("Environment manifest replay or downgrade")
        for accepted_raw, accepted_signature in db.execute("SELECT manifest, signature FROM authenticated"):
            accepted = verify_environment(
                bytes(accepted_raw), bytes(accepted_signature), self.trust, installed=True
            )
            if Version(manifest["version"]) < Version(accepted["version"]):
                raise ValueError("Automatic upstream downgrade is not allowed")

    def admit(self, identifier, raw, signature, wheel, *, probe):
        manifest = verify_environment(raw, signature, self.trust)
        with self._connect() as db:
            self._check_forward(db, manifest)
        if json.loads(self._inventory(identifier)) != manifest["files"]:
            raise ValueError("Candidate differs from signed inventory")
        verify_original_wheel(self.directory(identifier), wheel, manifest)
        # This is the first candidate execution; only authenticated bytes reach it.
        super().validate(
            identifier,
            version=manifest["version"],
            wheel_hash=manifest["wheel_sha256"],
            probe=probe,
            expected_inventory=manifest["files"],
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_forward(db, manifest)
            db.execute("INSERT INTO authenticated VALUES (?, ?, ?)", (identifier, raw, signature))
            db.execute(
                "UPDATE official_trust_state SET sequence=? WHERE singleton=1", (manifest["sequence"],)
            )

    def _verify(self, db, identifier):
        row = db.execute(
            "SELECT manifest, signature FROM authenticated WHERE environment=?", (identifier,)
        ).fetchone()
        if row is None:
            raise ValueError("Environment has no authenticated provenance")
        manifest = verify_environment(bytes(row[0]), bytes(row[1]), self.trust, installed=True)
        stored = db.execute(
            "SELECT version, wheel_hash, inventory FROM environments WHERE id=?", (identifier,)
        ).fetchone()
        if (
            stored is None
            or stored[0] != manifest["version"]
            or stored[1] != manifest["wheel_sha256"]
            or json.loads(stored[2]) != manifest["files"]
        ):
            raise ValueError("Stored environment differs from authenticated manifest")
        super()._verify(db, identifier)
