"""Task adapter for trusted, unmodified upstream packages in an isolated worker.

The application checks initial and resolved media URLs. Provider implementations
and their internal network clients remain owned by the upstream package.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from .errors import AppError
from .network import RequestGuard
from .official_bridge import preview_from_result
from .progress import ProgressReporter


class OfficialAdapter:
    def __init__(self, source, *, proxy=None, cookie=None, experimental=False, official_runtime=False):
        if not experimental and not official_runtime:
            raise AppError("OFFICIAL_NOT_ENABLED", "官方包任务链路尚未启用。", "check_engine")
        from parsehub import ParseHub

        self.hub = ParseHub()
        parser = self.hub.get_parser(source)
        if parser is None or parser.__platform__ is None:
            raise AppError("UNSUPPORTED_URL", "解析组件不支持此链接。", "check_url")
        self.platform = parser.__platform__.id
        if not official_runtime and self.platform not in {
            "douyin",
            "kuaishou",
            "xhs",
            "bilibili",
            "weixin_channels",
        }:
            raise AppError("PLATFORM_UNAVAILABLE", "该平台尚未完成官方包任务链路验证。", "check_engine")
        if self.platform == "weixin_channels" and not cookie:
            raise AppError("AUTH_REQUIRED", "请在本机配置腾讯元宝登录 Cookie 后重试。", "update_cookie")
        self.source, self.proxy, self.cookie = source, proxy, cookie

    def preview(self, result):
        raw = urlsplit(result.raw_url or self.source)
        query = urlencode(
            [(key, value) for key, value in parse_qsl(raw.query) if key in {"p", "id", "modal_id"}]
        )
        public_identity = raw._replace(query=query, fragment="").geturl()
        identity = hashlib.sha256(public_identity.encode()).hexdigest()
        return preview_from_result(result, source_identity=identity)

    async def inspect(self):
        await RequestGuard()(httpx.Request("GET", self.source))
        result = await asyncio.wait_for(
            self.hub.parse(self.source, proxy=self.proxy, cookie=self.cookie), 120
        )
        return result, self.preview(result)

    async def download(self, result, directory, progress, *, selection=None, expected_resource_id=None):
        preview = self.preview(result)
        if selection not in {None, "current"}:
            raise AppError("FORMAT_UNAVAILABLE", "所选格式不可用，请重新预览。", "inspect_again")
        if expected_resource_id and preview.resource_id != expected_resource_id:
            raise AppError("RESOURCE_CHANGED", "作品发生变化，请重新预览。", "inspect_again")
        items = (
            list(result.media)
            if isinstance(result.media, Sequence)
            else [result.media]
            if result.media
            else []
        )
        guard = RequestGuard()
        for item in items:
            for url in [item.url, *getattr(item, "backup_urls", []), getattr(item, "video_url", None)]:
                if url:
                    await guard(httpx.Request("GET", url))
        reporters = {}

        async def callback(current, total, unit, *_, **__):
            # Preserve the units actually reported by upstream, including albums.
            reporter = reporters.setdefault(unit, ProgressReporter(unit))
            payload = reporter.update(current, total)
            if payload is not None:
                await progress(payload)

        downloaded = await asyncio.wait_for(
            result.download(directory, proxy=self.proxy, callback=callback, connections=2, concurrency=2), 600
        )
        from parsehub.types import VideoRef

        from .hls_transfer import recover_playlist

        if isinstance(result.media, VideoRef):
            files = list(downloaded.output_dir.glob("*.mp4"))
            if len(files) == 1:
                await asyncio.wait_for(
                    recover_playlist(files[0], result.media.url, callback, proxy=self.proxy), 600
                )
        return downloaded
