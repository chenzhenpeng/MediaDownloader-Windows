"""Narrow, repeatable repairs for metadata and confirmed invalid saved responses."""

import json
import sqlite3
from pathlib import Path

from .errors import AppError
from .media_validation import validate_media_payloads
from .storage import valid_output_directory


def repair_durations(store):
    repairs = []
    for task in store.tasks():
        if task["platform"] != "kuaishou" or task["engine_version"] != "0.1.0.platforms-dev9":
            continue
        try:
            preview = json.loads(task["preview"])
            if preview.get("duration_repair") == 1:
                continue
            changed = False
            for media in preview.get("media", []):
                seconds = media.get("duration_seconds")
                if media.get("kind") == "video" and isinstance(seconds, (float, int)) and seconds > 0:
                    media["legacy_duration_milliseconds"] = seconds
                    media["duration_seconds"] = round(seconds / 1000, 3)
                    changed = True
            if changed:
                preview["duration_repair"] = 1
                repairs.append((task["id"], json.dumps(preview, ensure_ascii=False)))
        except (ValueError, TypeError, AttributeError):
            continue
    if repairs:
        backup = store.path.with_name(store.path.name + ".pre-history-repair-v1.bak")
        if not backup.exists():
            with sqlite3.connect(backup) as target:
                store.db.backup(target)
        with store.transaction():
            store.db.executemany(
                "UPDATE tasks SET preview=?,revision=revision+1 WHERE id=?",
                [(preview, key) for key, preview in repairs],
            )


def audit_outputs(jobs):
    invalid = []
    for task, paths in jobs:
        directory = Path(task["final_dir"])
        try:
            if not valid_output_directory(task["output_root"], directory, task["id"], task["attempt_id"]):
                continue
            files = []
            for value in paths:
                relative = Path(value)
                path = directory / relative
                if relative.is_absolute() or ".." in relative.parts or ":" in value:
                    continue
                if not path.resolve().is_relative_to(directory) or any(
                    p.is_symlink() or p.is_junction() for p in (path, *path.parents) if p != directory.parent
                ):
                    continue
                if path.is_file():
                    files.append(path)
            validate_media_payloads(files)
        except AppError:
            invalid.append((task["id"], task["attempt_id"], task["revision"]))
        except OSError:
            # Missing, moved or temporarily locked files are not evidence of corruption.
            continue
    return invalid
