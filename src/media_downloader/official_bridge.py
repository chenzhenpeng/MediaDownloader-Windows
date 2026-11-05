"""Candidate official-package boundary; not enabled in the production worker.

Only discovery and result conversion are exposed until network and execution
isolation have equivalent coverage to the existing worker.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import replace

from .contracts import Capability, MediaInfo, Preview
from .errors import AppError


def discover_capabilities() -> list[Capability]:
    from parsehub.parsers.base import BaseParser

    capabilities = {}
    for parser in BaseParser.get_registry():
        platform = parser.__platform__
        if platform is None:
            continue
        # These are upstream content categories, not promises of tested downloads.
        types = tuple(str(value) for value in parser.__supported_type__)
        previous = capabilities.get(platform.id)
        if previous:
            types = tuple(dict.fromkeys((*previous.media_types, *types)))
        capabilities[platform.id] = Capability(platform.id, platform.display_name, types)
    return list(capabilities.values())


def preview_from_result(result, *, source_identity: str) -> Preview:
    """Convert an official result without exposing media URLs or credential data.

    source_identity is an app-owned opaque identity, never a signed media URL.
    """
    if not isinstance(source_identity, str) or not source_identity:
        raise AppError("INVALID_RESOURCE", "作品标识无效，请重新解析。", "inspect_again")
    platform = result.platform
    if platform is None:
        raise AppError("PLATFORM_UNAVAILABLE", "解析结果缺少平台信息。", "check_engine")
    media = result.media
    items = list(media) if isinstance(media, Sequence) else [media] if media else []
    markdown = getattr(result, "markdown_content", None)
    content = getattr(result, "content", None)
    document = "md" if isinstance(markdown, str) and markdown.strip() else None
    if document is None and not items and isinstance(content, str) and content.strip():
        document = "txt"
    if not items and not document:
        raise AppError("NO_MEDIA", "该作品没有可下载的媒体。", "view_source")
    if len(items) > 500:
        raise AppError("TOO_MANY_MEDIA", "该作品的媒体数量超出当前支持范围。", "view_source")
    infos = []
    for item in items:
        extension = item.ext
        if not isinstance(extension, str) or not re.fullmatch(r"[a-zA-Z0-9]{1,8}", extension):
            raise AppError("UNSUPPORTED_FORMAT", "媒体格式无效，无法安全保存文件。", "view_source")
        duration = getattr(item, "duration", 0)
        if not isinstance(duration, (int, float)) or not math.isfinite(duration):
            duration = 0
        kind = type(item).__name__.removesuffix("Ref").lower()
        width, height = item.width or None, item.height or None
        # The official progressive Bilibili result copies source-post dimensions,
        # which can differ from the selected stream (verified 1080p vs 720p).
        # Do not advertise these as actual downloadable dimensions.
        if platform.id == "bilibili" and type(result).__name__ == "BiliVideoParseResult":
            width, height = None, None
        # Compatibility policy for the verified 2.4.0 provider units.
        if platform.id in {"douyin", "kuaishou"} and not (kind == "livephoto" and duration == 3):
            duration /= 1000
        infos.append(
            MediaInfo(
                kind,
                extension,
                width,
                height,
                round(duration, 3) if duration > 0 else None,
            )
        )
    if document:
        infos.append(MediaInfo("document", document, None, None, None))
    capability = next((item for item in discover_capabilities() if item.id == platform.id), None)
    if capability is None:
        capability = Capability(platform.id, platform.display_name, ())
    if any(item.kind == "livephoto" for item in infos):
        capability = replace(capability, live_photos=True)
    identity = hashlib.sha256(f"{platform.id}:{source_identity}".encode()).hexdigest()
    return Preview(
        result.title[:500] or "未命名作品",
        platform.id,
        identity,
        result.type.value,
        len(infos),
        tuple(infos),
        capability,
    )
