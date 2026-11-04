"""Exercise the frozen native backend through its actual private stdio contract."""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample")
    args = parser.parse_args()
    base = ROOT / "dist/native/MediaDownloader"
    data = ROOT / (
        ".local/n" + str(time.time_ns())[-8:] if args.sample else ".local/native/bridge-check"
    )
    env = dict(os.environ, MEDIA_DOWNLOADER_DATA_DIR=str(data))
    process = subprocess.Popen(
        [str(base / "backend/MediaBackend.exe"), "--engine-dir", str(base / "engine")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    events = queue.Queue()

    def read():
        for line in process.stdout:
            events.put(json.loads(line))

    threading.Thread(target=read, daemon=True).start()
    threading.Thread(target=lambda: process.stderr.read(), daemon=True).start()

    def send(identifier, method, params=None):
        process.stdin.write(
            json.dumps({"bridge": 1, "id": identifier, "method": method, "params": params or {}}) + "\n"
        )
        process.stdin.flush()

    report = {"bridge": False, "platforms": 0, "settings_persisted": False}
    try:
        send(1, "hello")
        send(2, "settings", {"theme": "dark"})
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            event = events.get(timeout=10)
            if event.get("event") == "response" and event.get("id") == 1:
                assert event["result"]["bridge"] == 1
                report["bridge"] = True
            if event.get("event") == "snapshot":
                snapshot = event["data"]
                report["platforms"] = sum(p["available"] for p in snapshot["platforms"])
                report["settings_persisted"] = snapshot["settings"]["theme"] == "dark"
                assert all("cookie" not in p and "proxy" not in p for p in snapshot["platforms"])
                if report["bridge"] and report["platforms"] == 24 and report["settings_persisted"]:
                    break
        assert report == {"bridge": True, "platforms": 24, "settings_persisted": True}, report
        if args.sample:
            send(10, "inspect", {"text": args.sample, "output_root": str(data / "d")})
            deadline = time.monotonic() + 160
            task_id, downloading = None, False
            while time.monotonic() < deadline:
                try:
                    event = events.get(timeout=5)
                except queue.Empty:
                    continue
                if event.get("event") == "response" and event.get("id") == 10:
                    assert "error" not in event, event
                    task_id = event["result"]["ids"][0]
                if event.get("event") != "snapshot" or not task_id:
                    continue
                tasks = event["data"].get("submitted", [])
                task = next((t for t in tasks if t["id"] == task_id), None)
                if not task:
                    continue
                assert task["state"] not in {"failed", "cancelled", "interrupted"}, (
                    task["state"],
                    task["error"],
                )
                if task["state"] == "ready" and not downloading:
                    downloading = True
                    send(11, "download", {"id": task_id})
                if task["state"] == "completed":
                    report["sample"] = {key: task[key] for key in ("state", "platform_name", "media", "size")}
                    assert task["size"] > 100000
                    break
            assert report.get("sample", {}).get("state") == "completed", report
        send(3, "shutdown")
        process.wait(timeout=15)
        assert process.returncode == 0
        output = ROOT / ("review/native/bridge-live.json" if args.sample else "review/native/bridge.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(report)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()

