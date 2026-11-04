"""Local engine descriptor. Signed update selection is a later milestone."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from . import ENGINE_VERSION, PROTOCOL, UPSTREAM_SHA


@dataclass(frozen=True)
class Engine:
    version: str
    upstream_sha: str
    program: str
    arguments: tuple[str, ...] = ()


def resolve_engine(directory: Path | None = None) -> Engine:
    if directory is None and not getattr(sys, "frozen", False):
        return Engine(ENGINE_VERSION, UPSTREAM_SHA, sys.executable, ("-m", "media_downloader.worker"))
    directory = (directory or Path(sys.executable).parent / "engine").resolve()
    manifest = json.loads((directory / "engine.json").read_text(encoding="utf-8"))
    if manifest["protocol"] != PROTOCOL or manifest["target"] != "windows-x86_64":
        raise ValueError("Incompatible engine")
    executable = directory / "media-engine.exe"
    if not executable.is_file():
        raise ValueError("Engine executable missing")
    return Engine(manifest["engine_version"], manifest["upstream_sha"], str(executable))


def tool_versions(engine: Engine) -> dict[str, str]:
    descriptor = Path(engine.program).parent / "engine.json"
    try:
        if descriptor.stat().st_size > 1_000_000:
            return {}
        metadata = json.loads(descriptor.read_text(encoding="utf-8"))
        return {
            "yt-dlp": metadata["yt-dlp"],
            **{name: metadata["tools"][name]["version"] for name in ("ffmpeg", "ffprobe")},
        }
    except (OSError, KeyError, ValueError):
        return {}
