"""Fetch a maintainer-configured, hash-pinned FFmpeg build ZIP for Windows CI."""

import hashlib
import os
import re
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from media_downloader.update_archive import no_reparse, safe_relative


def main():
    url, expected = os.environ["ENGINE_TOOLS_URL"], os.environ["ENGINE_TOOLS_SHA256"]
    if urlsplit(url).scheme != "https" or not re.fullmatch("[0-9a-f]{64}", expected):
        raise ValueError("Configure an HTTPS tool archive and its reviewed SHA-256")
    root = Path(".cache/ffmpeg").resolve()
    no_reparse(root)
    root.mkdir(parents=True, exist_ok=False)
    archive = root.parent / "ffmpeg-tools.zip"
    digest, count = hashlib.sha256(), 0
    with urllib.request.urlopen(url, timeout=30) as response, archive.open("xb") as output:
        if urlsplit(response.url).scheme != "https":
            raise ValueError("Tool redirect must remain HTTPS")
        while chunk := response.read(65536):
            count += len(chunk)
            if count > 1024**3:
                raise ValueError("Tool archive exceeds budget")
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("FFmpeg archive hash mismatch")
    with zipfile.ZipFile(archive) as bundle:
        if len(bundle.infolist()) > 3000 or sum(i.file_size for i in bundle.infolist()) > 2 * 1024**3:
            raise ValueError("Tool archive exceeds extraction budget")
        seen = set()
        for info in bundle.infolist():
            parts = safe_relative(info.filename)
            name = "/".join(parts).casefold()
            if name in seen or info.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError("Invalid tool entry")
            seen.add(name)
            target = root.joinpath(*parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, target.open("xb") as output:
                    while chunk := source.read(65536):
                        output.write(chunk)
    for relative in ("bin/ffmpeg.exe", "bin/ffprobe.exe", "LICENSE", "README.txt"):
        if not (root / relative).is_file():
            raise ValueError(f"Tool archive must contain {relative}")


if __name__ == "__main__":
    main()
