import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from parsehub.types import ImageRef, RichTextParseResult

from media_downloader.adapter import ParseHubAdapter, capabilities, load_parser, resource_identity
from media_downloader.contracts import platform_for_url
from media_downloader.network import RequestGuard
from media_downloader.platforms import PLATFORMS
from media_downloader.storage import extract_links, output_directory

SAMPLES = {
    "bilibili": "https://www.bilibili.com/video/BV123",
    "douyin": "https://www.douyin.com/video/123",
    "xhs": "https://www.xiaohongshu.com/explore/abc123",
    "kuaishou": "https://www.kuaishou.com/short-video/123",
    "weibo": "https://weibo.com/123/abc",
    "zhihu": "https://www.zhihu.com/question/123/answer/456",
    "tieba": "https://tieba.baidu.com/p/123",
    "toutiao": "https://www.toutiao.com/article/123",
    "weixin": "https://mp.weixin.qq.com/s/abc",
    "weixin_channels": "https://weixin.qq.com/sph/abc",
    "coolapk": "https://www.coolapk.com/feed/123",
    "douban": "https://www.douban.com/group/topic/123",
    "bangumi": "https://bgm.tv/blog/123",
    "xiaoheihe": "https://api.xiaoheihe.cn/v3/bbs/app/link?link_id=123",
    "pipix": "https://h5.pipix.com/ppx/item/123",
    "zuiyou": "https://share.xiaochuankeji.cn/hybrid/share/post?pid=123",
    "youtube": "https://www.youtube.com/watch?v=abc123",
    "tiktok": "https://www.tiktok.com/@someone/video/123",
    "instagram": "https://www.instagram.com/p/abc123/",
    "facebook": "https://www.facebook.com/watch?v=123",
    "twitter": "https://x.com/someone/status/123",
    "threads": "https://www.threads.com/@someone/post/abc",
    "snapchat": "https://www.snapchat.com/@someone/spotlight/abc",
    "medium": "https://medium.com/@someone/title-12345678",
}


def test_catalog_covers_every_upstream_parser_and_loads_independently():
    modules = {p.stem for p in Path("upstream-ParseHub/src/parsehub/parsers/parser").glob("*.py")}
    assert {spec.module for spec in PLATFORMS.values()} == modules - {"__init__"}
    assert set(SAMPLES) == set(PLATFORMS)
    items = capabilities()
    assert len(items) == 24 and all(item["available"] for item in items)
    for key in PLATFORMS:
        assert load_parser(key).__platform__.id == key


@pytest.mark.parametrize("platform,url", SAMPLES.items())
def test_all_platform_routes_parser_matches_and_output_folders(platform, url, tmp_path):
    assert platform_for_url(url) == platform
    assert extract_links(f"分享作品 {url}。") == [url]
    assert load_parser(platform).match(url)
    adapter = ParseHubAdapter(url, cookie="test=fixture" if PLATFORMS[platform].login_required else None)
    assert adapter.platform == platform and len(adapter.hub.parsers) == 1
    final = output_directory(tmp_path, platform, "作品标题", "a" * 32, "b" * 32)
    assert final.parent.name == PLATFORMS[platform].name.replace(" / ", "-")


@pytest.mark.parametrize("platform", list(PLATFORMS))
def test_network_guard_platform_aliases_and_lookalikes(platform, monkeypatch):
    async def public_addresses(*_):
        return {"1.1.1.1"}

    monkeypatch.setattr("media_downloader.network.resolve_addresses", public_addresses)
    for host in PLATFORMS[platform].hosts:
        assert platform_for_url(f"https://{host}.evil.test/x") is None
        assert platform_for_url(f"https://evil-{host}/x") is None
        # mp.weixin.qq.com must remain an article route rather than a video-channel route.
        assert platform_for_url(f"https://{host}/x") == platform
        asyncio.run(RequestGuard(platform)(httpx.Request("GET", f"https://{host}/x")))


def test_video_query_identities_are_distinct_and_aliases_are_stable():
    def identity(platform, url):
        return resource_identity(platform, SimpleNamespace(raw_url=url), url)

    assert identity("youtube", "https://youtube.com/watch?v=one") != identity(
        "youtube", "https://youtube.com/watch?v=two"
    )
    assert identity("youtube", "https://youtube.com/watch?v=one") == identity(
        "youtube", "https://youtu.be/one"
    )
    assert identity("facebook", "https://facebook.com/watch?v=one") != identity(
        "facebook", "https://facebook.com/watch?v=two"
    )
    assert identity("twitter", "https://x.com/person/status/123") == identity(
        "twitter", "https://twitter.com/person/status/123"
    )


def test_markdown_only_article_preview_and_download(tmp_path):
    adapter = ParseHubAdapter(SAMPLES["medium"])
    article = RichTextParseResult(title="文章标题", markdown_content="# 标题\n\n纯文字正文。")
    article.raw_url = SAMPLES["medium"]
    preview = adapter.preview(article)
    assert preview.media_type == "richtext" and preview.media[0].extension == "md"

    async def progress(_):
        pass

    article.name = "article"
    result = asyncio.run(adapter.download(article, tmp_path, progress))
    assert (result.output_dir / "正文.md").read_text(encoding="utf-8") == article.markdown_content


def test_article_images_and_body_are_both_preserved(tmp_path, monkeypatch):
    async def download_image(url, path, *args, **kwargs):
        Path(path).write_bytes(b"test-image")
        return Path(path)

    monkeypatch.setattr("parsehub.types.result.download", download_image)
    adapter = ParseHubAdapter(SAMPLES["medium"])
    article = RichTextParseResult(
        title="图文",
        media=[ImageRef(url="https://cdn.example/a.jpg", width=1, height=1)],
        markdown_content="# 图文\n\n正文。\n![图片](https://cdn.example/a.jpg)",
    )
    article.name = "article"

    async def progress(_):
        pass

    result = asyncio.run(adapter.download(article, tmp_path, progress))
    assert (result.output_dir / "001_article.jpg").read_bytes() == b"test-image"
    assert (result.output_dir / "正文.md").is_file()
    markdown = (result.output_dir / "正文.md").read_text(encoding="utf-8")
    assert "001_article.jpg" in markdown and "https://cdn.example" not in markdown


def test_zhihu_without_login_explains_connection_settings():
    from media_downloader.errors import AppError

    with pytest.raises(AppError) as error:
        ParseHubAdapter(SAMPLES["zhihu"])
    assert error.value.code == "AUTH_REQUIRED" and error.value.action == "update_cookie"


def test_channels_without_yuanbao_login_explains_credential_source():
    from media_downloader.errors import AppError

    with pytest.raises(AppError) as error:
        ParseHubAdapter("https://weixin.qq.com/sph/A55VXvUkXB")
    assert error.value.code == "AUTH_REQUIRED"
    assert "yuanbao.tencent.com" in error.value.message


def test_yt_cookie_used_for_parse_and_download_then_temp_file_removed(tmp_path, monkeypatch):
    from parsehub.parsers.base.ytdlp import YtVideoInfo, YtVideoParseResult
    from parsehub.types import VideoRef
    from parsehub.utils.helpers import SecretCookie

    adapter = ParseHubAdapter(SAMPLES["facebook"], cookie="session=test-cookie")
    parser = adapter.hub.parsers[0](cookie=SecretCookie("session=test-cookie"))
    assert ".facebook.com\t" in parser.get_cookie_text()
    info = YtVideoInfo("test", "", None, SAMPLES["facebook"], {}, width=1, height=1, duration=1)
    result = YtVideoParseResult(dl=info, video=VideoRef(url=SAMPLES["facebook"]))
    result.name = "video"
    cookie_paths = []

    async def run_download(self, cli_args, *, outtmpl, **kwargs):
        cookie_path = Path(cli_args[cli_args.index("--cookies") + 1])
        cookie_paths.append(cookie_path)
        assert ".facebook.com\t" in cookie_path.read_text(encoding="utf-8")
        Path(outtmpl.replace("%(ext)s", "mp4")).write_bytes(b"fixture-video")

    async def progress(_):
        pass

    monkeypatch.setattr(YtVideoParseResult, "_run_download", run_download)
    downloaded = asyncio.run(adapter.download(result, tmp_path, progress))
    assert (downloaded.output_dir / "video.mp4").is_file()
    assert cookie_paths and all(not path.exists() for path in cookie_paths)


def test_plain_text_post_is_saved_as_text(tmp_path):
    from parsehub.types import ImageParseResult

    adapter = ParseHubAdapter(SAMPLES["weixin"])
    result = ImageParseResult(title="文字帖子", content="纯文字内容")
    result.name = "post"
    assert adapter.preview(result).media[0].extension == "txt"

    async def progress(_):
        pass

    downloaded = asyncio.run(adapter.download(result, tmp_path, progress))
    assert (downloaded.output_dir / "正文.txt").read_text(encoding="utf-8") == "纯文字内容"
