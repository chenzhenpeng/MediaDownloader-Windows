"""Read official release metadata. This never downloads or executes upstream code."""

from __future__ import annotations

import re

import httpx

OFFICIAL_API = "https://api.github.com/repos/z-mio/ParseHub/releases/latest"
OFFICIAL_PAGE = "https://github.com/z-mio/ParseHub/releases"


def check_official_release(current_sha):
    try:
        with httpx.Client(timeout=6, follow_redirects=False) as client:
            with client.stream(
                "GET",
                OFFICIAL_API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "MediaDownloader-Windows"},
            ) as response:
                if response.status_code in {403, 429}:
                    return {"status": "error", "message": "官方源暂时限制了检查频率，请稍后重试。"}
                response.raise_for_status()
                raw = b""
                for chunk in response.iter_bytes():
                    raw += chunk
                    if len(raw) > 262144:
                        raise ValueError("Oversized metadata")
        import json

        value = json.loads(raw)
        tag = value["tag_name"]
        if not isinstance(tag, str) or not re.fullmatch(r"v?\d+(?:\.\d+){1,3}(?:[-.][a-zA-Z0-9.]+)?", tag):
            raise ValueError("Invalid release tag")
        same = value.get("target_commitish") == current_sha
        return {
            "status": "current" if same else "different",
            "tag": tag,
            "message": f"官方最新版本 {tag}，当前内核已基于此版本。"
            if same
            else f"官方最新版本 {tag}。安装更新仍需适配并签名的兼容内核包。",
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {"status": "error", "message": "暂时无法检查官方源，请检查网络后重试。"}
