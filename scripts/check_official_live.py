"""Opt-in public-link integration probe. Never reads the app credential store."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


async def check(source, *, download=None, ffprobe=None, max_bytes=100 * 1024**2):
    import httpx
    import parsehub
    from parsehub import ParseHub

    sys.path.insert(0, str(ROOT / "src"))
    from media_downloader.network import RequestGuard
    from media_downloader.official_bridge import preview_from_result

    # This checks the input and sample request, not every internal provider call.
    # Therefore the script remains an opt-in integration probe, not a worker API.
    await RequestGuard()(httpx.Request("GET", source))
    hub = ParseHub()
    result = await asyncio.wait_for(hub.parse(source), timeout=90)
    preview = preview_from_result(result, source_identity=hashlib.sha256(source.encode()).hexdigest())
    report = {
        "status": "parsed",
        "version": importlib.metadata.version("parsehub"),
        "package_origin": str(Path(parsehub.__file__).resolve().parent),
        "source_host": urlsplit(source).hostname,
        "used_app_cookie": False,
        "result_class": type(result).__name__,
        "preview": preview.to_dict(),
    }
    media = result.media
    if isinstance(media, (list, tuple)):
        media = media[0] if media else None
    if media is not None:
        referers = {"douyin": "https://www.douyin.com/", "kuaishou": "https://www.kuaishou.com/"}
        headers = {"Range": "bytes=0-65535"}
        if preview.platform in referers:
            headers["Referer"] = referers[preview.platform]
        async with httpx.AsyncClient(
            trust_env=False,
            timeout=20,
            follow_redirects=True,
            event_hooks={"request": [RequestGuard()]},
        ) as client:
            async with client.stream("GET", media.url, headers=headers) as response:
                sample = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    sample.extend(chunk[: 65536 - len(sample)])
                    if len(sample) >= 65536:
                        break
                report["media_probe"] = {
                    "http_status": response.status_code,
                    "content_type": response.headers.get("content-type", "")[:100],
                    "sample_bytes": len(sample),
                    "mp4_header": bytes(sample[4:8]) == b"ftyp",
                    "playlist_header": bytes(sample).lstrip().startswith(b"#EXTM3U"),
                }
                total = response.headers.get("content-range", "").rsplit("/", 1)[-1]
                if not total.isdigit() and response.status_code == 200:
                    total = response.headers.get("content-length", "")
                report["media_probe"]["declared_total_bytes"] = int(total) if total.isdigit() else None
    if download is not None:
        if media is None or not total.isdigit() or not 0 < int(total) <= max_bytes:
            report["status"] = "download_blocked"
            report["reason"] = "MEDIA_SIZE_UNKNOWN_OR_EXCEEDS_LIMIT"
            report["limit_bytes"] = max_bytes
            return report
        progress_events = 0

        async def progress(*_, **__):
            nonlocal progress_events
            progress_events += 1

        completed = await asyncio.wait_for(
            result.download(download, callback=progress, connections=2, concurrency=2), timeout=180
        )
        files = list(completed.output_dir.rglob("*.mp4"))
        if len(files) != 1 or files[0].stat().st_size != int(total):
            raise ValueError("Downloaded file size differs from media response")
        with files[0].open("rb") as stream:
            if stream.read(8)[4:8] != b"ftyp":
                raise ValueError("Downloaded file is not an MP4")
        report["download"] = {
            "bytes": files[0].stat().st_size,
            "progress_events": progress_events,
            "sha256": hashlib.sha256(files[0].read_bytes()).hexdigest(),
            "output_file": str(files[0].resolve()),
            "size_matches_server": True,
        }
        if ffprobe is not None:
            inspected = subprocess.run(
                [
                    str(ffprobe.resolve()),
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration:stream=codec_type,codec_name,width,height",
                    "-of",
                    "json",
                    str(files[0]),
                ],
                capture_output=True,
                timeout=30,
                creationflags=0x08000000,
            )
            if inspected.returncode:
                raise ValueError("Downloaded file failed ffprobe")
            metadata = json.loads(inspected.stdout)
            if not any(stream.get("codec_type") == "video" for stream in metadata.get("streams", [])):
                raise ValueError("Downloaded file has no video stream")
            report["download"]["ffprobe"] = metadata
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", type=Path)
    parser.add_argument("--ffprobe", type=Path)
    parser.add_argument("--max-mib", type=int, default=100, choices=range(1, 513), metavar="1..512")
    args = parser.parse_args()
    try:
        report = asyncio.run(
            asyncio.wait_for(
                check(
                    args.source,
                    download=args.download,
                    ffprobe=args.ffprobe,
                    max_bytes=args.max_mib * 1024**2,
                ),
                timeout=300 if args.download else 120,
            )
        )
    except Exception as exc:
        # Exception text/tracebacks may contain signed URLs or provider cookies.
        report = {"status": "failed", "error_type": type(exc).__name__, "used_app_cookie": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["status"] == "parsed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
