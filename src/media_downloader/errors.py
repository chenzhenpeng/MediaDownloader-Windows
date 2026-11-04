"""Classify failures without exporting third-party exception text or credentials."""

from __future__ import annotations

import errno
import socket
import sys
from dataclasses import asdict, dataclass

import httpx


@dataclass
class AppError(Exception):
    code: str
    message: str
    action: str = "retry"
    retryable: bool = False
    phase: str = "parsing"

    def to_dict(self):
        return asdict(self)


def error_chain(exc: BaseException):
    queue, seen = [exc], set()
    while queue and len(seen) < 32:
        current = queue.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        queue.extend(
            attempt.error
            for attempt in getattr(current, "attempts", ())
            if isinstance(getattr(attempt, "error", None), BaseException)
        )
        for cause in (current.__cause__, current.__context__):
            if cause is not None:
                queue.append(cause)


def classify_error(exc: BaseException, phase: str = "parsing") -> AppError:
    if isinstance(exc, AppError):
        exc.phase = phase
        return exc
    # Classification must still work when a required ParseHub DLL fails during import.
    upstream = sys.modules.get("parsehub.errors")
    ContentUnavailableError = getattr(upstream, "ContentUnavailableError", ())
    ParseHubError = getattr(upstream, "ParseHubError", ())
    ToolExecutionError = getattr(upstream, "ToolExecutionError", ())
    UnknownPlatform = getattr(upstream, "UnknownPlatform", ())

    chain = list(error_chain(exc))
    for current in chain:
        if isinstance(current, AppError):
            current.phase = phase
            return current
        if isinstance(current, OSError):
            if current.errno == errno.ENOSPC or getattr(current, "winerror", None) in {39, 112}:
                return AppError(
                    "DISK_FULL", "磁盘空间不足，请清理空间或更换保存位置。", "change_directory", phase=phase
                )
            if isinstance(current, PermissionError):
                return AppError(
                    "PERMISSION_DENIED",
                    "无法写入文件，请选择有写入权限的目录。",
                    "change_directory",
                    phase=phase,
                )
            if getattr(current, "winerror", None) in {126, 127, 193, 1114}:
                return AppError(
                    "CORE_DEPENDENCY_MISSING",
                    "内核运行组件无法加载，请检查安装或内核版本。",
                    "check_engine",
                    phase=phase,
                )
    statuses = set()
    for current in chain:
        status = getattr(current, "status_code", None)
        if isinstance(current, httpx.HTTPStatusError):
            status = current.response.status_code
        if isinstance(status, int):
            statuses.add(status)
    if 429 in statuses:
        return AppError("RATE_LIMITED", "平台限制了请求频率，请稍后重试。", "wait", phase=phase)
    if 401 in statuses:
        return AppError("AUTH_EXPIRED", "登录凭据无效或已过期，请更新 Cookie。", "update_cookie", phase=phase)
    if 403 in statuses:
        return AppError(
            "ACCESS_DENIED", "平台拒绝了访问，请检查链接、登录状态或网络。", "check_access", phase=phase
        )
    if any(isinstance(e, ContentUnavailableError) for e in chain):
        return AppError("CONTENT_UNAVAILABLE", "作品不存在、已删除或不可见。", "view_source", phase=phase)
    if any(isinstance(e, UnknownPlatform) for e in chain):
        return AppError("UNSUPPORTED_URL", "暂不支持此作品链接。", "check_url", phase=phase)
    for current in chain:
        if isinstance(current, ParseHubError):
            message = current.message.casefold()
            if "cookie" in message and any(word in message for word in ("无效", "失效", "过期")):
                return AppError(
                    "AUTH_EXPIRED", "登录凭据无效或已过期，请更新 Cookie。", "update_cookie", phase=phase
                )
            if any(word in message for word in ("需要登录", "登录后查看", "请登录")):
                return AppError(
                    "AUTH_REQUIRED", "该作品需要登录后访问，请设置平台 Cookie。", "update_cookie", phase=phase
                )
    if any(isinstance(e, ToolExecutionError) for e in chain):
        return AppError(
            "TOOL_FAILED", "媒体工具执行失败，请检查内核工具版本或稍后重试。", "check_engine", phase=phase
        )
    if any(isinstance(e, (TimeoutError, httpx.TimeoutException)) for e in chain):
        return AppError("NETWORK_TIMEOUT", "请求超时，请检查网络或代理后重试。", "check_network", True, phase)
    if any(isinstance(e, (httpx.HTTPError, socket.gaierror)) for e in chain):
        return AppError("NETWORK_ERROR", "网络请求失败，请检查连接或代理。", "check_network", True, phase)
    if any(isinstance(e, (ImportError, ModuleNotFoundError)) for e in chain):
        return AppError(
            "PLATFORM_UNAVAILABLE", "该平台的解析组件不可用，请检查内核版本。", "check_engine", phase=phase
        )
    if any(isinstance(e, FileNotFoundError) for e in chain):
        return AppError(
            "TOOL_MISSING" if phase == "startup" else "FILE_NOT_FOUND",
            "找不到执行工具，请检查内核安装。"
            if phase == "startup"
            else "找不到所需文件或目录，请检查保存位置。",
            "check_engine" if phase == "startup" else "change_directory",
            phase=phase,
        )
    if any(type(e).__module__.startswith("curl_cffi.") for e in chain):
        return AppError("NETWORK_ERROR", "平台网络请求失败，请检查网络或代理。", "check_network", True, phase)
    return AppError(
        "SAVE_FAILED"
        if phase == "finalizing"
        else "DOWNLOAD_FAILED"
        if phase == "downloading"
        else "PARSE_FAILED",
        "文件保存未完成，请检查保存位置。"
        if phase == "finalizing"
        else "下载未完成，请重试或检查作品是否仍可访问。"
        if phase == "downloading"
        else "作品解析失败，请检查链接和平台登录状态。",
        "retry",
        phase=phase,
    )
