"""M0 live sample acceptance. Input URLs remain in ignored local files."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from parsehub import ParseHub

ROOT = Path(__file__).resolve().parents[1]


async def one(sample, output, download, timeout, max_bytes):
    from parsehub.errors import ContentUnavailableError

    started = time.monotonic()
    result = {
        "id": sample["id"],
        "platform": sample["platform"],
        "category": sample["category"],
        "host": urlsplit(sample["url"]).hostname,
        "expected": sample["expected"],
        "parse": "not_run",
        "download": "not_run",
        "expectation_met": False,
    }
    proxy = os.environ.get("MEDIA_DOWNLOADER_M0_PROXY")
    cookie = os.environ.get(f"MEDIA_DOWNLOADER_M0_COOKIE_{sample['platform'].upper()}")
    result["proxy_used"], result["cookie_used"] = bool(proxy), bool(cookie)
    work = output / sample["id"]
    work.mkdir(parents=True, exist_ok=False)

    async def execute():
        parsed = await ParseHub().parse(sample["url"], proxy=proxy, cookie=cookie)
        result["parse"] = "passed"
        data = parsed.to_dict()
        media = data.get("media")
        result["media_type"] = data["type"]
        result["media_count"] = len(media) if isinstance(media, list) else int(bool(media))
        if sample["expected"] == "content_unavailable":
            return
        if not download:
            return
        if not media:
            result["download"] = "no_media"
            return
        result["download"] = "running"
        transfer = asyncio.create_task(parsed.download(work, proxy=proxy, connections=1, concurrency=1))
        try:
            while not transfer.done():
                await asyncio.sleep(0.25)
                size = sum(path.stat().st_size for path in work.rglob("*") if path.is_file())
                if size > max_bytes:
                    raise RuntimeError("Sample exceeds local disk budget")
            downloaded = await transfer
            files = [path for path in downloaded.output_dir.rglob("*") if path.is_file()]
            if not files or any(path.stat().st_size == 0 for path in files):
                raise RuntimeError("Empty media output")
            result["download"] = "passed"
            result["files"] = len(files)
            result["bytes"] = sum(path.stat().st_size for path in files)
            result["expectation_met"] = True
        finally:
            if not transfer.done():
                transfer.cancel()
                await asyncio.gather(transfer, return_exceptions=True)

    try:
        await asyncio.wait_for(execute(), timeout)
    except ContentUnavailableError:
        result["parse"] = "content_unavailable"
        result["expectation_met"] = sample["expected"] == "content_unavailable"
    except Exception as exc:
        result["error_type"] = type(exc).__name__  # no signed URLs, Cookie, or raw server responses
        if result["parse"] != "passed":
            result["parse"] = "failed"
        elif download:
            result["download"] = "failed"
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


async def run(args):
    samples = json.loads(args.samples.read_text(encoding="utf-8-sig"))
    ids = set()
    for sample in samples:
        if (
            sample["platform"] not in {"bilibili", "douyin", "xhs"}
            or sample["expected"] not in {"downloadable", "content_unavailable"}
            or not sample["id"].replace("-", "").replace("_", "").isalnum()
            or sample["id"] in ids
        ):
            raise ValueError("Invalid sample record")
        ids.add(sample["id"])
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for sample in samples:
        result = await one(sample, args.output, args.download, args.timeout, args.max_mib * 2**20)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    summary = {}
    for platform in ("bilibili", "douyin", "xhs"):
        expected = [r for r in results if r["platform"] == platform and r["expected"] == "downloadable"]
        parsed = sum(r["parse"] == "passed" for r in expected)
        downloaded = sum(r["download"] == "passed" for r in expected)
        summary[platform] = {
            "expected_downloadable": len(expected),
            "parse_passed": parsed,
            "download_passed": downloaded,
            "m0_gate": len(expected) >= 10
            and parsed / len(expected) >= 0.9
            and downloaded / len(expected) >= 0.9,
        }
    report = {
        "kind": "live_platform_samples",
        "download_enabled": args.download,
        "results": results,
        "summary": summary,
    }
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("samples", type=Path, help="Local JSON array of sample records")
    parser.add_argument("--output", type=Path, required=True, help="New output directory per run")
    parser.add_argument("--download", action="store_true", help="Verify full download, not just parsing")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-mib", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
