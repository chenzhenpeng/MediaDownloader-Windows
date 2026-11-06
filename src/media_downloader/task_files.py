"""Task-owned file operations. Never delete a user output directory."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path


def work_directory(root: str | Path, task_id: str, attempt_id: str) -> Path:
    if not all(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value) for value in (task_id, attempt_id)):
        raise ValueError("Invalid task ownership")
    return Path(root).resolve() / ".media-downloader-work" / task_id / attempt_id


def _regular_tree(directory: Path):
    with os.scandir(directory) as entries:
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if (
                entry.is_symlink()
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ValueError("Reparse points are not task-owned files")
            if entry.is_dir(follow_symlinks=False):
                yield from _regular_tree(Path(entry.path))
            else:
                yield Path(entry.path)


def validate_owned_directory(root, task_id, attempt_id) -> Path:
    directory = work_directory(root, task_id, attempt_id)
    for path in (directory.parent.parent, directory.parent, directory):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Task path is redirected")
    if directory.resolve() != directory or not directory.is_relative_to(Path(root).resolve()):
        raise ValueError("Task path escaped its output root")
    marker = directory / "owner.json"
    if marker.is_symlink() or marker.stat().st_size > 8192:
        raise ValueError("Invalid ownership marker")
    data = json.loads(marker.read_text(encoding="utf-8"))
    if data != {"task_id": task_id, "attempt_id": attempt_id}:
        raise ValueError("Ownership marker mismatch")
    return directory


def create_work_directory(root, task_id, attempt_id) -> Path:
    directory = work_directory(root, task_id, attempt_id)
    # Check ancestors before mkdir so a stale junction cannot redirect new writes.
    for path in (directory.parent.parent, directory.parent):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Task path is redirected")
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "owner.json").write_text(
        json.dumps({"task_id": task_id, "attempt_id": attempt_id}), encoding="utf-8"
    )
    return directory


def cleanup_work_directory(root, task_id, attempt_id) -> bool:
    target = work_directory(root, task_id, attempt_id)
    if not target.exists() and not target.is_symlink() and not target.is_junction():
        return True
    target = validate_owned_directory(root, task_id, attempt_id)
    list(_regular_tree(target))
    # Keep ownership evidence until every payload was removed, so sharing violations can retry.
    for child in target.iterdir():
        if child.name == "owner.json":
            continue
        if not child.resolve().is_relative_to(target):
            raise ValueError("Cleanup child escaped the owned directory")
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    (target / "owner.json").unlink()
    try:
        target.rmdir()
    except OSError:
        if target.is_dir() and not target.is_junction() and not target.is_symlink():
            atomic_json(target / "owner.json", {"task_id": task_id, "attempt_id": attempt_id})
        raise
    return True


def atomic_json(path: Path, value: dict):
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def build_manifest(directory: Path, command: dict, preview: dict, engine_version: str, upstream_sha: str):
    root = work_directory(command["output_root"], command["task_id"], command["attempt_id"])
    if not directory.resolve().is_relative_to(root):
        raise ValueError("Output escaped task directory")
    files = []
    for path in _regular_tree(directory):
        if path.name in {"manifest.json", "manifest.json.pending"}:
            continue
        if path.stat().st_size <= 0:
            raise ValueError("Empty output")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        files.append(
            {"path": path.relative_to(directory).as_posix(), "size": path.stat().st_size, "sha256": digest}
        )
    if not files:
        raise ValueError("Missing media output")
    return {
        "task_id": command["task_id"],
        "attempt_id": command["attempt_id"],
        "engine_version": engine_version,
        "upstream_sha": upstream_sha,
        "files": files,
        "preview": preview,
    }


def verify_output(root, final_dir, task_id, attempt_id, commit_token):
    from .media_paths import valid_output_directory

    directory = Path(final_dir)
    root = Path(root).resolve()
    if (
        not final_dir
        or not valid_output_directory(root, directory, task_id, attempt_id)
        or directory.resolve() != directory
        or directory.is_symlink()
        or directory.is_junction()
        or not directory.name.endswith(f"_{task_id[:8]}_{attempt_id[:6]}")
    ):
        raise ValueError("Invalid final directory")
    marker = directory / "manifest.json"
    if marker.is_symlink() or marker.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Invalid manifest")
    data = json.loads(marker.read_text(encoding="utf-8"))
    if data.get("task_id") != task_id or data.get("attempt_id") != attempt_id:
        raise ValueError("Output identity mismatch")
    if not commit_token or data.get("commit_token") != commit_token:
        raise ValueError("Commit token mismatch")
    files = data.get("files")
    if not isinstance(files, list) or not files or len(files) > 2000:
        raise ValueError("Invalid output list")
    actual = {path.relative_to(directory).as_posix() for path in _regular_tree(directory)}
    expected = {"manifest.json"}
    for item in files:
        relative = Path(item["path"])
        path = directory / relative
        if relative.is_absolute() or ".." in relative.parts or not path.resolve().is_relative_to(directory):
            raise ValueError("Output path escaped")
        if item["size"] <= 0 or not path.is_file() or path.stat().st_size != item["size"]:
            raise ValueError("Output size mismatch")
        digest = item.get("sha256")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("Output checksum mismatch")
        expected.add(relative.as_posix())
    if actual != expected:
        raise ValueError("Unexpected output files")
    if len(expected) != len(files) + 1:
        raise ValueError("Duplicate manifest paths")
    return data
