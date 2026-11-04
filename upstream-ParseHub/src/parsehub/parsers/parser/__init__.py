"""Lazy public exports: importing one parser must not import every platform SDK."""
from importlib import import_module

_EXPORTS = {
    "BangumiParser": "bangumi", "BiliParse": "bilibili", "BiliVideoParseResult": "bilibili",
    "BiliMusicParseResult": "bilibili", "CoolapkParser": "coolapk", "CoolapkImageParseResult": "coolapk",
    "CoolapkMultimediaParseResult": "coolapk", "CoolapkRichTextParseResult": "coolapk",
    "DoubanParser": "douban", "DoubanRichTextParseResult": "douban", "DouyinParser": "douyin",
    "FacebookParse": "facebook", "InstagramParser": "instagram", "MediumParser": "medium",
    "ThreadsParser": "threads", "TieBaParser": "tieba", "ToutiaoParser": "toutiao",
    "TwitterParser": "twitter", "WeiboParser": "weibo", "WXParser": "weixin",
    "WXChannelsParser": "wxchannels", "XHSParser": "xhs", "XiaoHeiHeParser": "xiaoheihe",
    "YtbParse": "youtube", "ZuiYouParser": "zuiyou",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module(f"{__name__}.{_EXPORTS[name]}"), name)
    globals()[name] = value
    return value

