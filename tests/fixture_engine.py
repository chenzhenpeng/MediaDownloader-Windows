"""Test-only local provider. Not installed as an application entry point."""

import asyncio
import os

from parsehub import ParseHub
from parsehub.types import ImageParseResult, ImageRef, RichTextParseResult


async def parse_fixture(self, source, **kwargs):
    if os.environ.get("TEST_CRASH_ID") and source.endswith(os.environ["TEST_CRASH_ID"]):
        os._exit(17)
    if expected := os.environ.get("TEST_COOKIE_EXPECTED"):
        assert kwargs.get("cookie") == expected
    if delay := os.environ.get("TEST_DELAY"):
        await asyncio.sleep(float(delay))
    from media_downloader.contracts import platform_for_url

    if platform_for_url(source) == os.environ.get("TEST_ARTICLE_PLATFORM"):
        return RichTextParseResult(title="本地图文验证", markdown_content="# 本地文章\n\n离线正文。")
    return ImageParseResult(
        title="本地下载验证", photo=[ImageRef(url=os.environ["TEST_MEDIA_URL"], width=10, height=10)]
    )


ParseHub.parse = parse_fixture

import media_downloader.adapter as adapter  # noqa: E402


class LocalTestGuard:
    def __init__(self, *args):
        pass

    async def __call__(self, request):
        assert request.url.host == "127.0.0.1"


adapter.RequestGuard = LocalTestGuard

from media_downloader.worker import main  # noqa: E402

raise SystemExit(main())
