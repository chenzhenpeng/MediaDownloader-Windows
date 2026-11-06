"""Fetch the exact reviewed tools used by local and GitHub runtime builds."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from media_downloader.update_archive import no_reparse

ROOT = Path(__file__).resolve().parents[1]


def fetch(url, path, expected):
    if urlsplit(url).scheme != "https":
        raise ValueError("HTTPS required")
    digest, size = hashlib.sha256(), 0
    with httpx.Client(follow_redirects=True, timeout=120) as client, client.stream("GET", url) as response:
        response.raise_for_status()
        if any(item.url.scheme != "https" for item in [*response.history, response]):
            raise ValueError("Tool redirect must remain HTTPS")
        with path.open("xb") as stream:
            for chunk in response.iter_bytes(1024 * 1024):
                size += len(chunk)
                if size > 512 * 1024**2:
                    raise ValueError("Tool exceeds download budget")
                digest.update(chunk)
                stream.write(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("Tool does not match reviewed hash")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".cache/media-tools-ci")
    parser.add_argument("--sevenzip", type=Path)
    parser.add_argument("--ffmpeg-only", action="store_true")
    args = parser.parse_args()
    lock = json.loads((ROOT / "packaging/media-tools-lock.json").read_bytes())
    root = args.output.resolve()
    no_reparse(root)
    root.mkdir(parents=True, exist_ok=False)
    archive = root / "ffmpeg.7z"
    fetch(lock["ffmpeg"]["url"], archive, lock["ffmpeg"]["sha256"])
    tool = str(args.sevenzip.resolve(strict=True)) if args.sevenzip else shutil.which("7z")
    if not tool:
        raise RuntimeError("The build runner requires 7-Zip")
    # Extraction is permitted only after authenticating the entire pinned archive.
    subprocess.run(
        [tool, "x", str(archive), f"-o{root / 'extracted'}", "-y"], check=True, stdout=subprocess.DEVNULL
    )
    bins = list((root / "extracted").glob("*/bin/ffmpeg.exe"))
    if len(bins) != 1:
        raise ValueError("Unexpected FFmpeg archive layout")
    source = bins[0].parent.parent
    destination = root / "ffmpeg"
    (destination / "bin").mkdir(parents=True)
    for name in ("ffmpeg", "ffprobe"):
        file = source / f"bin/{name}.exe"
        with file.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != lock["ffmpeg"][f"{name}_sha256"]:
                raise ValueError("FFmpeg executable hash mismatch")
        shutil.copy2(file, destination / "bin" / file.name)
    for name in ("LICENSE", "README.txt"):
        shutil.copy2(source / name, destination / name)
    if not args.ffmpeg_only:
        fetch(lock["yt-dlp"]["url"], root / "yt-dlp.exe", lock["yt-dlp"]["sha256"])
    print("Verified media tools against media-tools-lock.json")


if __name__ == "__main__":
    main()
