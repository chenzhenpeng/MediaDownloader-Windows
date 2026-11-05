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
    runtime_id: str = ""
    runtime_version: str = ""
    parser_version: str = ""
    component: str = "engine"
    parser_component_version: str = ""


def resolve_engine(directory: Path | None = None, *, runtime: Engine | None = None) -> Engine:
    if directory is None and not getattr(sys, "frozen", False):
        return Engine(ENGINE_VERSION, UPSTREAM_SHA, sys.executable, ("-m", "media_downloader.worker"))
    directory = (directory or Path(sys.executable).parent / "engine").resolve()
    manifest = json.loads((directory / "engine.json").read_text(encoding="utf-8"))
    if manifest["protocol"] != PROTOCOL or manifest["target"] != "windows-x86_64":
        raise ValueError("Incompatible engine")
    if manifest.get("component") == "parsehub":
        if not runtime or not runtime.runtime_id or runtime.runtime_id != manifest.get("requires_runtime_id"):
            raise ValueError("ParseHub component requires an updated client runtime")
        if not (directory / "python/parsehub/__init__.py").is_file():
            raise ValueError("ParseHub component code is missing")
        return Engine(
            manifest["engine_version"],
            manifest["upstream_sha"],
            runtime.program,
            (*runtime.arguments, "--component-dir", str(directory)),
            runtime.runtime_id,
            runtime.runtime_version or runtime.version,
            manifest.get("parsehub_version", ""),
            "parsehub",
            manifest["engine_version"],
        )
    executable = directory / "media-engine.exe"
    if not executable.is_file():
        raise ValueError("Engine executable missing")
    return Engine(
        manifest["engine_version"],
        manifest["upstream_sha"],
        str(executable),
        (),
        manifest.get("runtime_id", ""),
        manifest["engine_version"],
        manifest.get("parsehub_version", ""),
        "engine",
        manifest.get("parser_component_version", manifest["engine_version"]),
    )


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
