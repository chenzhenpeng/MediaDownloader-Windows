"""HTTPS allowlist and bounded streaming for signed feeds; explicit local QA feeds."""

from __future__ import annotations

import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

import httpx

from .update_archive import no_reparse
from .update_contracts import UpdateError, fail


class UpdateFeed:
    def __init__(self, trust, *, transport=None):
        self.trust, self.transport = trust, transport

    def chunks(self, url, *, cancelled=lambda: False, expected_size=None, start=0, end_limit=None):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(30, connect=10),
                trust_env=False,
                transport=self.transport,
                headers={"Accept-Encoding": "identity"},
            ) as client:
                position = start
                while True:
                    end = min(position + 4 * 1024**2, expected_size) - 1 if expected_size else None
                    if end_limit is not None:
                        end = min(end, end_limit)
                    headers = {"Range": f"bytes={position}-{end}"} if expected_size else {}
                    for _ in range(5):
                        if cancelled():
                            fail("UPDATE_CANCELLED", "更新已取消。")
                        self.trust.check_url(url)
                        with client.stream("GET", url, headers=headers) as response:
                            if response.is_redirect:
                                url = urljoin(url, response.headers.get("location", ""))
                                continue
                            response.raise_for_status()
                            partial = response.status_code == 206
                            if partial:
                                expected_range = f"bytes {position}-{end}/{expected_size}"
                                if (
                                    not expected_size
                                    or response.headers.get("content-range") != expected_range
                                ):
                                    fail("UPDATE_NETWORK", "更新服务器返回了不匹配的文件分段。")
                            elif position:
                                fail("UPDATE_NETWORK", "更新服务器未继续返回请求的文件分段。")
                            if response.headers.get("content-encoding", "identity").lower() != "identity":
                                fail("UPDATE_NETWORK", "更新服务器返回了不支持的传输编码。")
                            count = 0
                            for chunk in response.iter_raw(65536):
                                if cancelled():
                                    fail("UPDATE_CANCELLED", "更新已取消。")
                                count += len(chunk)
                                if partial and count > end - position + 1:
                                    fail("UPDATE_HASH", "更新文件分段超出预期大小。")
                                yield chunk
                            if not partial:
                                return  # Servers without Range support may return the complete body.
                            if count != end - position + 1:
                                fail("UPDATE_HASH", "更新文件分段不完整。")
                            position += count
                            if position == expected_size or end_limit is not None and position > end_limit:
                                return
                            break
                    else:
                        fail("UPDATE_NETWORK", "更新地址跳转次数过多。")
        except httpx.HTTPError as exc:
            raise UpdateError("UPDATE_NETWORK", "无法连接更新源，请检查网络后重试。") from exc

    def artifact_chunks(self, url, total, *, cancelled=lambda: False):
        block = 4 * 1024**2
        first = 0
        for chunk in self.chunks(
            url, cancelled=cancelled, expected_size=total, end_limit=min(block, total) - 1
        ):
            first += len(chunk)
            yield chunk
        if first == total:
            return  # Includes full-body fallback when Range is unsupported.

        def fetch(start):
            return b"".join(
                self.chunks(
                    url,
                    cancelled=cancelled,
                    expected_size=total,
                    start=start,
                    end_limit=min(start + block, total) - 1,
                )
            )

        # Bound buffered responses and preserve archive order despite parallel requests.
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="engine-range") as pool:
            pending = deque()
            starts = iter(range(first, total, block))
            for start in starts:
                pending.append(pool.submit(fetch, start))
                if len(pending) == 4:
                    break
            while pending:
                body = pending.popleft().result()
                if cancelled():
                    fail("UPDATE_CANCELLED", "更新已取消。")
                yield body
                start = next(starts, None)
                if start is not None:
                    pending.append(pool.submit(fetch, start))

    def bounded(self, url, maximum, *, cancelled=lambda: False):
        data = bytearray()
        for chunk in self.chunks(url, cancelled=cancelled):
            data.extend(chunk)
            if len(data) > maximum:
                fail("UPDATE_MANIFEST", "更新清单超出大小限制。")
        return bytes(data)

    def check(self, *, cancelled=lambda: False):
        if not self.trust.configured:
            fail("UPDATE_UNCONFIGURED", "尚未配置受信任的更新源。")
        if self.trust.local_feed:
            directory = self.trust.local_feed
            no_reparse(directory)
            for name, limit in (("catalog.json", 2 * 1024**2), ("catalog.sig", 64)):
                path = directory / name
                no_reparse(path)
                if path.stat().st_size > limit:
                    fail("UPDATE_MANIFEST", "本地更新清单大小无效。")
            return (directory / "catalog.json").read_bytes(), (directory / "catalog.sig").read_bytes()
        return (
            self.bounded(
                self.trust.catalog_url,
                2 * 1024**2,
                cancelled=cancelled,
            ),
            self.bounded(self.trust.catalog_signature_url, 64, cancelled=cancelled),
        )

    def download(self, manifest, directory, *, cancelled=lambda: False, progress=lambda done, total: None):
        directory = Path(directory)
        no_reparse(directory)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / (uuid.uuid4().hex + ".zip.part")
        total = manifest["size_bytes"]
        done = 0
        try:
            with destination.open("xb") as output:
                if self.trust.local_feed:
                    source = self.trust.local_feed / "engine.zip"
                    no_reparse(source)
                    with source.open("rb") as stream:
                        while chunk := stream.read(65536):
                            if cancelled():
                                fail("UPDATE_CANCELLED", "更新已取消。")
                            done += len(chunk)
                            if done > total:
                                fail("UPDATE_HASH", "更新包大小超出签名清单。")
                            output.write(chunk)
                            progress(done, total)
                else:
                    for chunk in self.artifact_chunks(manifest["artifact_url"], total, cancelled=cancelled):
                        done += len(chunk)
                        if done > total:
                            fail("UPDATE_HASH", "更新包大小超出签名清单。")
                        output.write(chunk)
                        progress(done, total)
            if done != total:
                fail("UPDATE_HASH", "更新包下载不完整。")
            return destination
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
