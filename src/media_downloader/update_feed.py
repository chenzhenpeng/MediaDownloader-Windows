"""HTTPS allowlist and bounded streaming for signed feeds; explicit local QA feeds."""

from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import urljoin

import httpx

from .update_archive import no_reparse
from .update_contracts import UpdateError, fail


class UpdateFeed:
    def __init__(self, trust, *, transport=None):
        self.trust, self.transport = trust, transport

    def chunks(self, url, *, cancelled=lambda: False):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(20, connect=10),
                trust_env=False,
                transport=self.transport,
                headers={"Accept-Encoding": "identity"},
            ) as client:
                for _ in range(5):
                    self.trust.check_url(url)
                    with client.stream("GET", url) as response:
                        if response.is_redirect:
                            url = urljoin(url, response.headers.get("location", ""))
                            continue
                        response.raise_for_status()
                        if response.headers.get("content-encoding", "identity").lower() != "identity":
                            fail("UPDATE_NETWORK", "更新服务器返回了不支持的传输编码。")
                        for chunk in response.iter_raw(65536):
                            if cancelled():
                                fail("UPDATE_CANCELLED", "更新已取消。")
                            yield chunk
                        return
                fail("UPDATE_NETWORK", "更新地址跳转次数过多。")
        except httpx.HTTPError as exc:
            raise UpdateError("UPDATE_NETWORK", "无法连接更新源，请检查网络后重试。") from exc

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
            for name, limit in (("release.json", 131072), ("release.sig", 64)):
                path = directory / name
                no_reparse(path)
                if path.stat().st_size > limit:
                    fail("UPDATE_MANIFEST", "本地更新清单大小无效。")
            return (directory / "release.json").read_bytes(), (directory / "release.sig").read_bytes()
        return (
            self.bounded(self.trust.manifest_url, 131072, cancelled=cancelled),
            self.bounded(self.trust.signature_url, 64, cancelled=cancelled),
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
                    for chunk in self.chunks(manifest["artifact_url"], cancelled=cancelled):
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
