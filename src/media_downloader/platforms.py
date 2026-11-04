"""Client-owned catalog for the 24 parsers in the pinned ParseHub revision.

No parser imports: routing, UI labels, settings and output folders share this catalog.
Media types describe adapter support, not a claim of live-platform acceptance.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    module: str
    parser: str
    hosts: tuple[str, ...]
    media_types: tuple[str, ...]
    login_required: bool = False
    credential_hint: str = ""


PLATFORMS = {
    "bilibili": PlatformSpec(
        "哔哩哔哩",
        "bilibili",
        "BiliParse",
        ("bilibili.com", "b23.tv", "bili2233.cn"),
        ("video", "image", "music"),
    ),
    "douyin": PlatformSpec(
        "抖音", "douyin", "DouyinParser", ("douyin.com", "iesdouyin.com"), ("video", "image")
    ),
    "xhs": PlatformSpec(
        "小红书", "xhs", "XHSParser", ("xiaohongshu.com", "xhslink.com", "xhslink.cn"), ("video", "image")
    ),
    "kuaishou": PlatformSpec(
        "快手", "kuaishou", "KuaiShouParser", ("kuaishou.com", "chenzhongtech.com"), ("video", "image")
    ),
    "weibo": PlatformSpec(
        "微博", "weibo", "WeiboParser", ("weibo.com", "weibo.cn"), ("video", "image", "text")
    ),
    "zhihu": PlatformSpec(
        "知乎", "zhihu", "ZhihuParser", ("zhihu.com",), ("video", "image", "article", "text"), True
    ),
    "tieba": PlatformSpec("百度贴吧", "tieba", "TieBaParser", ("tieba.baidu.com",), ("video", "image")),
    "toutiao": PlatformSpec(
        "今日头条", "toutiao", "ToutiaoParser", ("toutiao.com",), ("video", "image", "article")
    ),
    "weixin": PlatformSpec(
        "微信公众号", "weixin", "WXParser", ("mp.weixin.qq.com",), ("image", "article", "text")
    ),
    "weixin_channels": PlatformSpec(
        "微信视频号",
        "wxchannels",
        "WXChannelsParser",
        ("weixin.qq.com", "channels.weixin.qq.com"),
        ("video",),
        True,
        "需要腾讯元宝（yuanbao.tencent.com）的登录 Cookie，不是微信 Cookie。请仅在本机填写。",
    ),
    "coolapk": PlatformSpec("酷安", "coolapk", "CoolapkParser", ("coolapk.com",), ("image", "article")),
    "douban": PlatformSpec("豆瓣", "douban", "DoubanParser", ("douban.com", "douc.cc"), ("image", "article")),
    "bangumi": PlatformSpec(
        "Bangumi", "bangumi", "BangumiParser", ("bgm.tv", "bangumi.tv", "chii.in"), ("image", "article")
    ),
    "xiaoheihe": PlatformSpec(
        "小黑盒", "xiaoheihe", "XiaoHeiHeParser", ("xiaoheihe.cn",), ("video", "image", "article")
    ),
    "pipix": PlatformSpec("皮皮虾", "pipix", "PipixParser", ("pipix.com",), ("video", "image")),
    "zuiyou": PlatformSpec(
        "最右", "zuiyou", "ZuiYouParser", ("xiaochuankeji.cn", "izuiyou.com"), ("video", "image")
    ),
    "youtube": PlatformSpec("YouTube", "youtube", "YtbParse", ("youtube.com", "youtu.be"), ("video",)),
    "tiktok": PlatformSpec("TikTok", "tiktok", "TikTokParser", ("tiktok.com",), ("video", "image")),
    "instagram": PlatformSpec(
        "Instagram", "instagram", "InstagramParser", ("instagram.com",), ("video", "image")
    ),
    "facebook": PlatformSpec("Facebook", "facebook", "FacebookParse", ("facebook.com",), ("video",)),
    "twitter": PlatformSpec(
        "X / Twitter",
        "twitter",
        "TwitterParser",
        ("x.com", "twitter.com", "fixupx.com"),
        ("video", "image", "article"),
    ),
    "threads": PlatformSpec("Threads", "threads", "ThreadsParser", ("threads.com",), ("video", "image")),
    "snapchat": PlatformSpec("Snapchat", "snapchat", "Snapchatarse", ("snapchat.com",), ("video",)),
    "medium": PlatformSpec("Medium", "medium", "MediumParser", ("medium.com",), ("image", "article")),
}
