"""Application-owned protocol models. No dependency on ParseHub objects."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .platforms import PLATFORMS

PLATFORM_HOSTS = {key: spec.hosts for key, spec in PLATFORMS.items()}


def validate_command(command: dict, protocol: int):
    from .errors import AppError

    valid = isinstance(command, dict) and command.get("protocol") == protocol
    valid = (
        valid and isinstance(command.get("action"), str) and command.get("action") in {"inspect", "download"}
    )
    for key in ("task_id", "attempt_id"):
        value = command.get(key) if isinstance(command, dict) else None
        valid = valid and isinstance(value, str) and bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value))
    source = command.get("source") if isinstance(command, dict) else None
    directory = command.get("output_root") if isinstance(command, dict) else None
    valid = valid and isinstance(source, str) and isinstance(directory, str) and Path(directory).is_absolute()
    for key in ("proxy", "selection", "expected_resource_id"):
        valid = valid and (command.get(key) is None or isinstance(command.get(key), str))
    valid = valid and (command.get("cookie") is None or isinstance(command.get("cookie"), (str, dict)))
    if not valid:
        raise AppError("INVALID_COMMAND", "内核收到无效命令，请检查客户端与内核版本。", "check_engine")


def platform_for_url(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80, 443}
        ):
            return None
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    # Specific hosts (e.g. mp.weixin.qq.com) take precedence over parent domains.
    for platform, domains in sorted(
        PLATFORM_HOSTS.items(), key=lambda item: max(map(len, item[1])), reverse=True
    ):
        if any(
            host == domain
            or (platform not in {"weixin", "weixin_channels", "tieba"} and host.endswith("." + domain))
            for domain in domains
        ):
            return platform
    return None


@dataclass(frozen=True)
class Capability:
    id: str
    name: str
    media_types: tuple[str, ...]
    cookie_supported: bool = True
    format_selection: bool = False
    live_photos: bool = False
    status: str = "experimental"
    available: bool = True
    error_code: str | None = None

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class MediaInfo:
    kind: str
    extension: str
    width: int | None
    height: int | None
    duration_seconds: float | None


@dataclass(frozen=True)
class Preview:
    title: str
    platform: str
    resource_id: str
    media_type: str
    media_count: int
    media: tuple[MediaInfo, ...]
    capability: Capability

    def to_dict(self):
        return asdict(self)
