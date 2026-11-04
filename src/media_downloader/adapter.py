"""The only runtime boundary converting ParseHub types to application contracts."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import math
import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from .contracts import Capability, MediaInfo, Preview, platform_for_url
from .errors import AppError
from .network import RequestGuard
from .platforms import PLATFORMS
from .progress import ProgressReporter

PARSERS = {
    key: (spec.module, spec.parser, Capability(key, spec.name, spec.media_types))
    for key, spec in PLATFORMS.items()
}


def netscape_cookie(values, domain):
    if not values:
        return None
    lines = ["# Netscape HTTP Cookie File"]
    for name, value in values.items():
        if any(char in str(name) + str(value) for char in "\r\n\t"):
            raise AppError("INVALID_COOKIE", "Cookie 格式无效，请重新填写。", "update_cookie")
        lines.append(f".{domain}\tTRUE\t/\tFALSE\t0\t{name}\t{value}")
    return "\n".join(lines) + "\n"


def document_content(result):
    markdown = getattr(result, "markdown_content", None)
    if isinstance(markdown, str) and markdown.strip():
        return markdown, "md"
    text = getattr(result, "content", None)
    if not result.media and isinstance(text, str) and text.strip():
        return text, "txt"
    return None


def load_parser(platform: str):
    module, symbol, _ = PARSERS[platform]
    try:
        return getattr(importlib.import_module(f"parsehub.parsers.parser.{module}"), symbol)
    except Exception as exc:
        raise AppError(
            "PLATFORM_UNAVAILABLE", "该平台的解析组件加载失败，请检查内核版本。", "check_engine"
        ) from exc


def capabilities() -> list[dict]:
    result = []
    for platform, (_, _, capability) in PARSERS.items():
        try:
            load_parser(platform)
        except AppError:
            capability = replace(capability, available=False, error_code="PLATFORM_UNAVAILABLE")
        result.append(capability.to_dict())
    return result


def resource_identity(platform, result, source):
    url = urlsplit(result.raw_url or source)
    parameters = dict(parse_qsl(url.query))
    if platform == "douyin":
        matched = re.search(r"/(?:video|note|slides)/(\d+)", url.path)
        identifier = matched.group(1) if matched else parameters.get("modal_id")
        if identifier:
            return hashlib.sha256(f"douyin:{identifier}".encode()).hexdigest()
    elif platform == "bilibili":
        matched = re.search(r"/video/((?:BV[0-9a-zA-Z]+)|(?:av\d+))", url.path)
        if matched:
            return hashlib.sha256(
                f"bilibili:{matched.group(1)}:{parameters.get('p', '1')}".encode()
            ).hexdigest()
    elif platform == "xhs":
        matched = re.search(r"/(?:explore|discovery/item)/([0-9a-fA-F]+)", url.path)
        if matched:
            return hashlib.sha256(f"xhs:{matched.group(1).lower()}".encode()).hexdigest()
    elif platform == "youtube":
        matched = re.search(r"/(?:shorts|embed)/([^/]+)", url.path)
        identifier = (
            url.path.strip("/")
            if url.hostname == "youtu.be"
            else parameters.get("v") or (matched.group(1) if matched else None)
        )
        if identifier:
            return hashlib.sha256(f"youtube:{identifier}".encode()).hexdigest()
    elif platform == "twitter":
        matched = re.search(r"/status/(\d+)", url.path)
        if matched:
            return hashlib.sha256(f"twitter:{matched.group(1)}".encode()).hexdigest()
    # Keep content identifiers, never tracking/signature/login parameters.
    identity_keys = {"p", "modal_id", "v", "pid", "id", "link_id", "__biz", "mid", "idx", "sn"}
    query = urlencode(sorted((key, value) for key, value in parse_qsl(url.query) if key in identity_keys))
    identity = f"{platform}:{url.hostname}:{url.path}:{query}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class ParseHubAdapter:
    def __init__(self, source: str, *, proxy=None, cookie=None):
        self.platform = platform_for_url(source)
        if self.platform is None:
            raise AppError("UNSUPPORTED_URL", "暂不支持此作品链接，请检查平台和地址。", "check_url")
        parsed_source = urlsplit(source)
        host = (parsed_source.hostname or "").lower().rstrip(".")
        netloc = host + (f":{parsed_source.port}" if parsed_source.port is not None else "")
        source = parsed_source._replace(netloc=netloc).geturl()
        parser_type = load_parser(self.platform)
        if PLATFORMS[self.platform].login_required and not cookie:
            hint = (
                PLATFORMS[self.platform].credential_hint
                or "该平台需要登录后访问，请先在设置中填写平台 Cookie。"
            )
            raise AppError(
                "AUTH_REQUIRED",
                hint,
                "update_cookie",
            )
        request_guard = RequestGuard(self.platform)

        class GuardedParser(parser_type, register=False):
            def get_cookie_text(self):
                # Generic yt-dlp platforms otherwise discard the user's Cookie.
                return netscape_cookie(self.cookie.get_value(), PLATFORMS[platform].hosts[0])

        platform = self.platform
        GuardedParser.request_guard = request_guard
        from parsehub import ParseHub

        self.hub = ParseHub(parsers=[GuardedParser])
        self.source, self.proxy, self.cookie = source, proxy, cookie

    async def inspect(self):
        parsed = await asyncio.wait_for(
            self.hub.parse(self.source, proxy=self.proxy, cookie=self.cookie), 120
        )
        return parsed, self.preview(parsed)

    def preview(self, result) -> Preview:
        media = (
            list(result.media)
            if isinstance(result.media, Sequence)
            else [result.media]
            if result.media
            else []
        )
        article = document_content(result)
        if not media and article is None:
            raise AppError("NO_MEDIA", "该作品没有可下载的媒体。", "view_source")
        if len(media) > 500:
            raise AppError("TOO_MANY_MEDIA", "该作品的媒体数量超出当前支持范围。", "view_source")
        infos = []
        for item in media:
            for extension in (item.ext, getattr(item, "video_ext", "mp4")):
                if not extension or not re.fullmatch(r"[a-zA-Z0-9]{1,8}", extension):
                    raise AppError("UNSUPPORTED_FORMAT", "媒体格式无效，无法安全保存文件。", "view_source")
            duration = getattr(item, "duration", 0)
            if not isinstance(duration, (int, float)) or not math.isfinite(duration):
                duration = 0
            # Douyin's provider copies API milliseconds; the app contract always uses seconds.
            kind = type(item).__name__.removesuffix("Ref").lower()
            seconds = (
                duration / 1000
                if self.platform in {"douyin", "kuaishou"} and not (kind == "livephoto" and duration == 3)
                else duration
            )
            infos.append(
                MediaInfo(
                    kind,
                    item.ext,
                    item.width or None,
                    item.height or None,
                    round(seconds, 3) if seconds > 0 else None,
                )
            )
        if article:
            infos.append(MediaInfo("document", article[1], None, None, None))
        return Preview(
            result.title[:500] or "未命名作品",
            self.platform,
            resource_identity(self.platform, result, self.source),
            result.type.value,
            len(infos),
            tuple(infos),
            PARSERS[self.platform][2],
        )

    async def download(self, result, directory, progress, *, selection=None, expected_resource_id=None):
        preview = self.preview(result)
        if selection not in {None, "current"}:
            raise AppError("FORMAT_UNAVAILABLE", "所选格式当前不可用，请重新预览。", "inspect_again")
        if expected_resource_id and expected_resource_id != preview.resource_id:
            raise AppError("RESOURCE_CHANGED", "链接指向的作品发生变化，请重新预览确认。", "inspect_again")
        from parsehub.parsers.base.ytdlp import YtVideoParseResult
        from parsehub.utils.downloader import SegmentDownloader

        kind = (
            "percent"
            if isinstance(result, YtVideoParseResult)
            else "count"
            if isinstance(result.media, Sequence)
            else "bytes"
        )
        reporter = ProgressReporter(kind)

        async def callback(current, total, unit, *args, **kwargs):
            payload = reporter.update(current, total)
            if payload is not None:
                await progress(payload)

        previous_guard = SegmentDownloader.request_guard
        original_run = None
        if isinstance(result, YtVideoParseResult) and self.cookie:
            from parsehub.parsers.base.ytdlp import _materialize_cookie
            from parsehub.utils.helpers import SecretCookie

            cookie_text = netscape_cookie(
                SecretCookie(self.cookie).get_value(), PLATFORMS[self.platform].hosts[0]
            )
            original_run = result._run_download

            async def run_with_cookie(cli_args, **kwargs):
                with _materialize_cookie(cookie_text) as cookie_args:
                    await original_run([*cli_args, *cookie_args], **kwargs)

            result._run_download = run_with_cookie
        SegmentDownloader.request_guard = RequestGuard()
        try:
            downloaded = await result.download(
                directory, proxy=self.proxy, callback=callback, connections=2, concurrency=2
            )
            article = document_content(result)
            if article:
                content = article[0]
                if article[1] == "md":
                    refs = list(result.media) if isinstance(result.media, Sequence) else []
                    files = list(downloaded.media) if isinstance(downloaded.media, Sequence) else []
                    for ref, file in zip(refs, files, strict=False):
                        relative = Path(file.path).relative_to(downloaded.output_dir)
                        content = content.replace(ref.url, quote(relative.as_posix(), safe="/"))
                (downloaded.output_dir / f"正文.{article[1]}").write_text(content, encoding="utf-8")
            return downloaded
        finally:
            SegmentDownloader.request_guard = previous_guard
            if original_run is not None:
                result._run_download = original_run
