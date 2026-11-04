from __future__ import annotations

import asyncio
import ipaddress
import socket
import time

import httpx

from .contracts import platform_for_url
from .errors import AppError

FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


async def resolve_addresses(host: str, port: int):
    addresses = await asyncio.wait_for(
        asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
        7,
    )
    return {item[4][0] for item in addresses}


class RequestGuard:
    def __init__(self, platform: str | None = None):
        self.platform = platform
        self.cache: dict[tuple[str, int], float] = {}
        self.fake_ip_mapping: bool | None = None

    async def __call__(self, request: httpx.Request):
        url = request.url
        if url.scheme not in {"http", "https"} or url.username or url.password or not url.host:
            raise AppError("UNSAFE_URL", "链接包含不允许的协议或地址。", "check_url")
        if url.host == "localhost" or url.host.endswith((".localhost", ".local", ".internal", ".home.arpa")):
            raise AppError("UNSAFE_URL", "链接指向本地网络，已停止访问。", "check_url")
        if self.platform and platform_for_url(str(url)) != self.platform:
            raise AppError("UNSAFE_REDIRECT", "分享链接跳转到了非预期平台，已停止访问。", "check_url")
        key = (url.host, url.port or (443 if url.scheme == "https" else 80))
        if self.cache.get(key, 0) > time.monotonic():
            return
        try:
            literal = ipaddress.ip_address(url.host)
            if not literal.is_global:
                raise AppError("UNSAFE_URL", "媒体链接包含本地/私有 IP 地址，已停止访问。", "check_url")
            addresses = {str(literal)}
        except ValueError:
            addresses = await resolve_addresses(*key)
        parsed_addresses = [ipaddress.ip_address(address) for address in addresses]
        fake_mapping = bool(parsed_addresses) and all(
            address in FAKE_IP_NETWORK for address in parsed_addresses
        )
        if fake_mapping and self.fake_ip_mapping is None:
            # Some Windows TUN proxies map all public names into the benchmark range.
            # Confirm the same mapping for an independent, fixed public domain.
            sentinel = await resolve_addresses("www.microsoft.com", 443)
            self.fake_ip_mapping = bool(sentinel) and all(
                ipaddress.ip_address(address) in FAKE_IP_NETWORK for address in sentinel
            )
        if (
            not addresses
            or any(not address.is_global for address in parsed_addresses)
            and not (fake_mapping and self.fake_ip_mapping)
        ):
            raise AppError("UNSAFE_URL", "作品或媒体链接指向本地/私有网络，已停止访问。", "check_url")
        self.cache[key] = time.monotonic() + 60
