"""Reject manifests and error documents masquerading as completed binary media."""

from .errors import AppError


def validate_media_payloads(files):
    extensions = {".mp4", ".mov", ".mkv", ".webm", ".m4a", ".mp3", ".jpg", ".jpeg", ".png", ".webp", ".gif"}
    for path in files:
        if path.suffix.lower() not in extensions:
            continue
        with path.open("rb") as stream:
            header = stream.read(512).lstrip(b"\xef\xbb\xbf \r\n\t")
        if header.startswith(b"#EXTM3U") or b"<MPD" in header:
            raise AppError(
                "STREAM_NOT_DOWNLOADED",
                "下载地址返回了分段播放列表，尚未取得完整视频，请更新内核或重试。",
                "check_engine",
            )
        if header.lower().startswith((b"<!doctype html", b"<html", b"<head")):
            raise AppError(
                "INVALID_MEDIA_RESPONSE",
                "媒体地址返回了网页，未保存为下载成功，请检查登录状态或重试。",
                "check_access",
            )
