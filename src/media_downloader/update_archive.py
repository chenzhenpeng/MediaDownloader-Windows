"""Exact inventory validation and extraction into a newly-created staging directory."""

from __future__ import annotations

import hashlib
import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from .update_contracts import digest_file, fail, strict_json


def safe_relative(name):
    parts = PurePosixPath(name).parts
    if (
        not parts
        or name.startswith("/")
        or "\\" in name
        or "\x00" in name
        or any(
            part in {".", ".."}
            or part.endswith((" ", "."))
            or re.search(r'[<>:"|?*\x00-\x1f]', part)
            or PureWindowsPath(part).is_reserved()
            for part in parts
        )
        or PurePosixPath(name).as_posix() != name.rstrip("/")
    ):
        fail("UPDATE_ARCHIVE", "内核包包含无效或越界路径。")
    return parts


def no_reparse(path):
    for entry in [path, *path.parents]:
        if (
            entry.is_symlink()
            or entry.is_junction()
            or entry.exists()
            and getattr(entry.lstat(), "st_file_attributes", 0) & 0x400
        ):
            fail("UPDATE_PATH", "内核更新目录包含链接或重解析点，已停止操作。")


def extract_archive(archive: Path, target: Path, manifest, *, cancelled=lambda: False):
    no_reparse(target)
    target.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as bundle:
        entries, names, total = bundle.infolist(), {}, 0
        if len(entries) > manifest["file_count"] + 1000 or len(entries) > 21000:
            fail("UPDATE_ARCHIVE", "内核包文件数量超出清单限制。")
        for info in entries:
            parts = safe_relative(info.filename)
            name = "/".join(parts).casefold()
            mode = info.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if (
                name in names
                or kind not in {0, stat.S_IFREG, stat.S_IFDIR}
                or info.external_attr & 0x400
                or info.flag_bits & 1
                or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            ):
                fail("UPDATE_ARCHIVE", "内核包包含重复、链接或不支持的文件条目。")
            names[name] = info.is_dir()
            total += info.file_size
            if total > manifest["unpacked_size_bytes"]:
                fail("UPDATE_ARCHIVE", "内核包解压大小超出签名清单。")
        if (
            total != manifest["unpacked_size_bytes"]
            or sum(not info.is_dir() for info in entries) != manifest["file_count"]
        ):
            fail("UPDATE_ARCHIVE", "内核包大小或数量与签名清单不一致。")
        for name in names:
            for parent in PurePosixPath(name).parents:
                if parent.as_posix() in names and not names[parent.as_posix()]:
                    fail("UPDATE_ARCHIVE", "内核包的文件与目录路径冲突。")
        if shutil.disk_usage(target).free < total + 100 * 1024**2:
            fail("UPDATE_DISK", "磁盘空间不足，无法安装内核更新。")
        for info in entries:
            if cancelled():
                fail("UPDATE_CANCELLED", "更新已取消，当前内核保持可用。")
            destination = target.joinpath(*safe_relative(info.filename))
            no_reparse(destination)
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with bundle.open(info) as source, destination.open("xb") as output:
                while chunk := source.read(65536):
                    if cancelled():
                        fail("UPDATE_CANCELLED", "更新已取消，当前内核保持可用。")
                    written += len(chunk)
                    if written > info.file_size:
                        fail("UPDATE_ARCHIVE", "内核文件大小超出清单。")
                    output.write(chunk)
            if written != info.file_size:
                fail("UPDATE_ARCHIVE", "内核文件不完整。")
    verify_inventory(target, manifest)


def verify_inventory(directory: Path, manifest):
    no_reparse(directory)
    inventory = directory / "files.json"
    no_reparse(inventory)
    if inventory.stat().st_size > 8 * 1024**2 or digest_file(inventory) != manifest["inventory_sha256"]:
        fail("UPDATE_INVENTORY", "内核文件清单未通过签名哈希验证。")
    try:
        entries = strict_json(inventory.read_bytes())
        if not isinstance(entries, dict) or len(entries) != manifest["file_count"] - 1:
            raise ValueError("Invalid inventory")
        actual = set()
        for path in directory.rglob("*"):
            no_reparse(path)
            if path.is_file():
                actual.add(path.relative_to(directory).as_posix())
        if actual != set(entries) | {"files.json"}:
            raise ValueError("Unexpected files")
        for relative, metadata in entries.items():
            parts = safe_relative(relative)
            path = directory.joinpath(*parts)
            if (
                type(metadata["size"]) is not int
                or metadata["size"] != path.stat().st_size
                or digest_file(path) != metadata["sha256"]
            ):
                raise ValueError("File mismatch")
    except (ValueError, TypeError, KeyError) as exc:
        from .update_contracts import UpdateError

        raise UpdateError("UPDATE_INVENTORY", "已安装内核文件缺失、被修改或包含额外文件。") from exc


def inventory_bytes(directory):
    import json

    entries = {}
    for path in sorted(directory.rglob("*")):
        no_reparse(path)
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            safe_relative(relative)
            if relative == "files.json":
                fail("UPDATE_PACKAGE", "构建目录中不应包含旧 files.json。")
            entries[relative] = {"size": path.stat().st_size, "sha256": digest_file(path)}
    raw = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest(), entries
