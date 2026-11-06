from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath

from .platforms import PLATFORMS

PLATFORM_FOLDERS = {key: spec.name.replace(" / ", "-") for key, spec in PLATFORMS.items()}


def output_directory(root, platform, title, task_id, attempt_id) -> Path:
    parent = Path(root).resolve() / PLATFORM_FOLDERS[platform]
    # Reserve room for the ownership suffix and a title-bearing media filename.
    budget = min(70, (240 - len(str(parent)) - 40) // 2)
    if budget < 8:
        from .errors import AppError

        raise AppError("PATH_TOO_LONG", "保存位置路径过长，请选择较短的下载目录。", "change_directory")
    name = safe_name(title)[:budget].rstrip(" .")
    name = safe_name(name)
    return parent / f"{name}_{task_id[:8]}_{attempt_id[:6]}"


def valid_output_directory(root, directory, task_id, attempt_id) -> bool:
    root, directory = Path(root).resolve(), Path(directory)
    parent = directory.parent
    allowed = parent.parent == root and parent.name in PLATFORM_FOLDERS.values()
    return (
        allowed
        and directory.resolve() == directory
        and not parent.is_symlink()
        and not parent.is_junction()
        and not directory.is_symlink()
        and not directory.is_junction()
        and directory.name.endswith(f"_{task_id[:8]}_{attempt_id[:6]}")
    )


def safe_name(value: str) -> str:
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", value).strip(" .")[:70].rstrip(" .")
    if PureWindowsPath(name).is_reserved():
        name = "_" + name
    return name or "未命名作品"


def download_stem(title: str, working_directory: Path) -> str:
    from .errors import AppError

    budget = min(70, (240 - len(str(working_directory.resolve())) - 24) // 2)
    if budget < 8:
        raise AppError("PATH_TOO_LONG", "保存位置路径过长，请选择较短的下载目录。", "change_directory")
    return safe_name(safe_name(title)[:budget].rstrip(" ."))


