"""Local engine descriptor. Signed update selection is a later milestone."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
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
    components: dict[str, str] = field(default_factory=dict)
    component_versions: dict[str, str] = field(default_factory=dict)


def resolve_engine(directory: Path | None = None, *, runtime: Engine | None = None) -> Engine:
    if directory is None and not getattr(sys, "frozen", False):
        return Engine(ENGINE_VERSION, UPSTREAM_SHA, sys.executable, ("-m", "media_downloader.worker"))
    directory = (directory or Path(sys.executable).parent / "engine").resolve()
    if (directory / "profile.json").is_file():
        from .execution_profile import load_bundle

        return load_bundle(directory)
    manifest = json.loads((directory / "engine.json").read_text(encoding="utf-8"))
    if manifest["protocol"] != PROTOCOL or manifest["target"] != "windows-x86_64":
        raise ValueError("Incompatible engine")
    if manifest.get("layout") == "official-embedded":
        if not (directory / "python.exe").is_file() or not (directory / "worker_entry.py").is_file():
            raise ValueError("Official runtime is incomplete")
        return Engine(
            manifest["engine_version"],
            manifest["upstream_sha"],
            str(directory / "python.exe"),
            ("-B", "-I", str(directory / "worker_entry.py")),
            manifest["runtime_id"],
            manifest["engine_version"],
            manifest["parsehub_version"],
            "engine",
            manifest["parsehub_version"],
        )
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
    if engine.components:
        from .execution_profile import descriptor

        tools = descriptor(engine.components["media-tools"], "media-tools")
        python = descriptor(engine.components["python-runtime"], "python-runtime")
        return {"yt-dlp": python["contract"]["dependencies"].get("yt-dlp", ""),
                **{name: tools["versions"][name]["version"] for name in ("ffmpeg", "ffprobe")}}
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
