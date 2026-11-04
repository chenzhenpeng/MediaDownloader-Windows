import pytest

from media_downloader import PROTOCOL
from media_downloader.ui_capabilities import capability_copy


def test_capability_copy_only_lists_available_client_platforms():
    description = {
        "protocol": PROTOCOL,
        "engine_version": "test",
        "capabilities": [
            {
                "id": "bilibili",
                "name": "哔哩哔哩",
                "available": True,
                "media_types": ["video", "image", "music"],
            },
            {"id": "douyin", "name": "抖音", "available": True, "media_types": ["video", "image"]},
            {"id": "xhs", "name": "小红书", "available": False, "media_types": ["image"]},
            {"id": "youtube", "name": "YouTube", "available": True, "media_types": ["video"]},
        ],
    }
    assert capability_copy(description, "test") == [
        ("哔哩哔哩", "视频、图片 / 图集、音频"),
        ("抖音", "视频、图片 / 图集"),
        ("YouTube", "视频"),
    ]
    with pytest.raises(ValueError):
        capability_copy(description, "different")


def test_capability_copy_updates_after_core_change_without_static_platform_list():
    description = {
        "protocol": PROTOCOL,
        "engine_version": "new",
        "capabilities": [
            {"id": "xhs", "name": "小红书", "available": True, "media_types": ["image"], "live_photos": True}
        ],
    }
    assert capability_copy(description, "new") == [("小红书", "图片 / 图集、实况照片")]
