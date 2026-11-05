"""Opt-in original-package image/Live Photo integration check; no app credentials."""

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def check(source, output, ffmpeg):
    import httpx
    from parsehub import ParseHub
    from PIL import Image

    sys.path.insert(0, str(ROOT / "src"))
    from media_downloader.network import RequestGuard
    from media_downloader.official_bridge import preview_from_result

    await RequestGuard()(httpx.Request("GET", source))
    result = await asyncio.wait_for(ParseHub().parse(source), 90)
    preview = preview_from_result(result, source_identity=hashlib.sha256(source.encode()).hexdigest())
    refs = result.media
    if not isinstance(refs, (list, tuple)) or not 1 <= len(refs) <= 30:
        raise ValueError("Expected a gallery within 30 items")
    urls = [ref.url for ref in refs]
    urls += [ref.video_url for ref in refs if getattr(ref, "video_url", None)]
    semaphore = asyncio.Semaphore(4)
    async with httpx.AsyncClient(
        trust_env=False,
        timeout=20,
        follow_redirects=True,
        event_hooks={"request": [RequestGuard()]},
    ) as client:

        async def size(url):
            async with semaphore:
                async with client.stream("GET", url, headers={"Range": "bytes=0-0"}) as response:
                    response.raise_for_status()
                    total = response.headers.get("content-range", "").rsplit("/", 1)[-1]
                    if not total.isdigit() and response.status_code == 200:
                        total = response.headers.get("content-length", "")
                    if not total.isdigit() or int(total) <= 0:
                        raise ValueError("Unknown gallery resource size")
                    return int(total)

        sizes = await asyncio.gather(*(size(url) for url in urls))
    if sum(sizes) > 200 * 1024**2:
        raise ValueError("Gallery exceeds integration sample limit")
    progress_events = []

    async def progress(current, total, unit, *_, **__):
        progress_events.append((current, total, unit))

    downloaded = await asyncio.wait_for(
        result.download(output, callback=progress, connections=2, concurrency=2), 180
    )
    files = list(downloaded.media)
    if len(files) != len(refs):
        raise ValueError("Gallery item count mismatch")
    records, all_paths = [], []
    for index, (ref, item) in enumerate(zip(refs, files, strict=True), 1):
        path = Path(item.path)
        if not path.resolve().is_relative_to(downloaded.output_dir.resolve()):
            raise ValueError("Gallery output escaped directory")
        if not path.name.startswith(f"{index:03d}_"):
            raise ValueError("Gallery numbering does not match parse order")
        with Image.open(path) as image:
            image.load()
            dimensions = list(image.size)
        if path.stat().st_size != sizes[index - 1]:
            raise ValueError("Image size mismatch")
        all_paths.append(path)
        record = {"index": index, "image": path.name, "dimensions": dimensions}
        video = getattr(item, "video_path", None)
        if bool(video) != bool(getattr(ref, "video_url", None)):
            raise ValueError("Live Photo video missing")
        if video:
            video = Path(video)
            if not video.resolve().is_relative_to(downloaded.output_dir.resolve()):
                raise ValueError("Live Photo video escaped directory")
            if not video.name.startswith(f"{index:03d}_"):
                raise ValueError("Live Photo pairing mismatch")
            decoded = subprocess.run(
                [str(ffmpeg.resolve()), "-v", "error", "-i", str(video), "-f", "null", "-"],
                capture_output=True,
                timeout=30,
                creationflags=0x08000000,
            )
            if decoded.returncode or decoded.stderr.strip():
                raise ValueError("Live Photo failed full decode")
            record["video"] = video.name
            all_paths.append(video)
        records.append(record)
    if sum(path.stat().st_size for path in all_paths) != sum(sizes):
        raise ValueError("Gallery total size mismatch")
    if not progress_events or progress_events[-1] != (len(refs), len(refs), "count"):
        raise ValueError("Gallery progress did not complete")
    return {
        "status": "passed",
        "used_app_cookie": False,
        "preview": preview.to_dict(),
        "image_count": len(files),
        "live_video_count": len(all_paths) - len(files),
        "total_bytes": sum(sizes),
        "numbering_matches_parse_order": True,
        "images_fully_decoded": True,
        "live_videos_fully_decoded": True,
        "progress_events": len(progress_events),
        "items": records,
        "output_directory": str(downloaded.output_dir.resolve()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = asyncio.run(asyncio.wait_for(check(args.source, args.download, args.ffmpeg), 330))
    except Exception as exc:
        report = {"status": "failed", "error_type": type(exc).__name__, "used_app_cookie": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps({key: value for key, value in report.items() if key not in {"preview", "items"}}, indent=2)
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
