"""Drive the production TaskService against an explicit frozen engine and local sample list."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from media_downloader.engine import resolve_engine
from media_downloader.service import TaskService
from media_downloader.storage import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("samples", type=Path)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--engine-dir", type=Path)
    choice.add_argument(
        "--source", action="store_true", help="Exercise the source worker instead of a frozen core"
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    samples = json.loads(args.samples.read_text(encoding="utf-8-sig"))
    args.output.mkdir(parents=True, exist_ok=False)
    app = QCoreApplication([])
    engine = resolve_engine(args.engine_dir)
    store = Store(args.output / "tasks.sqlite3")
    service = TaskService(store, engine=engine)
    # The parent Python is already running; frozen children receive no Python/tool PATH entries.
    os.environ["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    results = []
    try:
        for sample in samples:
            started = time.monotonic()
            service.submit([sample["url"]], str(args.output))
            task_id = store.tasks()[0]["id"]
            download_requested = False
            while True:
                app.processEvents()
                task = store.get(task_id)
                if task["state"] == "ready" and not service.running and not download_requested:
                    service.retry(task_id)
                    download_requested = True
                elif (
                    task["state"] in {"completed", "failed", "interrupted", "cancelled"}
                    and not service.running
                ):
                    break
                if time.monotonic() - started > 180:
                    service.cancel(task_id)
                    service.shutdown()
                    raise TimeoutError("Live frozen sample timed out")
                time.sleep(0.01)
            files = (
                [p for p in Path(task["final_dir"]).rglob("*") if p.is_file() and p.name != "manifest.json"]
                if task["state"] == "completed"
                else []
            )
            result = {
                "id": sample["id"],
                "platform": sample["platform"],
                "state": task["state"],
                "error_code": task.get("error_code", ""),
                "engine_version": task["engine_version"],
                "upstream_sha": task["upstream_sha"],
                "files": len(files),
                "bytes": sum(p.stat().st_size for p in files),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "path_stripped": True,
                "output_dir": task["final_dir"],
            }
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        service.shutdown()
        store.close()
    (args.output / "report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if any(result["state"] != "completed" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
