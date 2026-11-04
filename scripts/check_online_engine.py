"""Exercise the frozen backend's real HTTPS update and rollback in isolated data."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / ".local/online-engine" / str(time.time_ns())
    output.mkdir(parents=True)
    distribution = ROOT / "dist/native/MediaDownloader"
    environment = dict(os.environ, MEDIA_DOWNLOADER_DATA_DIR=str(output / "data"))
    inbox = queue.Queue()
    with (output / "backend.stderr").open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [str(distribution / "backend/MediaBackend.exe"), "--engine-dir", str(distribution / "engine")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            env=environment,
            creationflags=0x08000000,
        )

        def read():
            for line in process.stdout:
                inbox.put(json.loads(line))

        threading.Thread(target=read, daemon=True).start()
        states = []

        def send(method, params=None):
            process.stdin.write(json.dumps({"id": 1, "method": method, "params": params or {}}) + "\n")
            process.stdin.flush()

        def wait_status(target, timeout=600):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    event = inbox.get(timeout=2)
                except queue.Empty:
                    if process.poll() is not None:
                        raise RuntimeError("Frozen backend exited unexpectedly") from None
                    continue
                if event.get("event") != "snapshot":
                    continue
                snapshot = event["data"]
                update = snapshot["update"]
                status = update["status"]
                if not states or states[-1] != status:
                    states.append(status)
                    print(f"Online update: {status}", flush=True)
                if status == "failed":
                    raise RuntimeError(update["message"])
                if target is None or status == target:
                    return snapshot
            raise TimeoutError(f"Update did not reach {target}")

        try:
            before = wait_status(None)
            assert before["update"]["configured"]
            send("update", {"action": "check"})
            wait_status("available")
            send("update", {"action": "install"})
            upgraded = wait_status("updated")
            assert upgraded["engine_version"] != before["engine_version"]
            assert upgraded["update"]["can_rollback"]
            send("update", {"action": "rollback"})
            reverted = wait_status("rolled_back", timeout=120)
            assert reverted["engine_version"] == before["engine_version"]
            policy = json.loads((output / "data/update-policy.json").read_bytes())
            report = {
                "passed": True,
                "scope": "Frozen production backend; actual GitHub HTTPS feed; isolated data",
                "before": before["engine_version"],
                "upgraded": upgraded["engine_version"],
                "rollback": reverted["engine_version"],
                "sequence_after_rollback": policy["sequence"],
                "states": states,
            }
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2), flush=True)
        finally:
            if process.poll() is None:
                send("shutdown")
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
