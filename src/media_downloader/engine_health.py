"""Bounded isolated candidate probes, with kill-on-close process-tree ownership."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from . import PROTOCOL
from .update_contracts import fail
from .windows import ProcessJob


def probe_engine(engine, *, cancelled=lambda: False):
    with tempfile.TemporaryDirectory(prefix="media-engine-probe-") as temporary:
        root = Path(temporary)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in {
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "LOCALAPPDATA",
                "APPDATA",
                "USERPROFILE",
                "PROGRAMDATA",
            }
        }
        environment.update(
            PATH=str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"),
            PYTHONIOENCODING="utf-8",
            PYTHONUTF8="1",
            PYTHONDONTWRITEBYTECODE="1",
        )
        for action in ("--describe", "--self-test"):
            arguments = [engine.program, *engine.arguments, action]
            if action == "--self-test":
                arguments += ["--output", str(root / "outputs")]
            with (root / "stdout").open("wb") as output, (root / "stderr").open("wb") as errors:
                process = subprocess.Popen(
                    arguments,
                    cwd=root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=errors,
                    creationflags=0x08000000,
                )
                job = None
                try:
                    job = ProcessJob(process.pid)
                    deadline = time.monotonic() + (25 if action == "--describe" else 90)
                    while process.poll() is None:
                        if cancelled():
                            fail("UPDATE_CANCELLED", "更新已取消。")
                        if time.monotonic() > deadline:
                            fail("UPDATE_HEALTH", "候选内核自检超时，当前内核未更改。")
                        if (root / "stdout").stat().st_size + (root / "stderr").stat().st_size > 8 * 1024**2:
                            fail("UPDATE_HEALTH", "候选内核自检输出异常。")
                        time.sleep(0.05)
                    if process.returncode:
                        fail("UPDATE_HEALTH", "候选内核无法启动或自检失败。")
                finally:
                    if job:
                        job.close()
                    if process.poll() is None:
                        process.kill()
                    process.wait()
            try:
                raw = (root / "stdout").read_bytes()
                if len(raw) > 1024**2:
                    raise ValueError("Oversize health report")
                data = json.loads(raw)
                if (
                    data["protocol"] != PROTOCOL
                    or data["engine_version"] != engine.version
                    or data["upstream_sha"] != engine.upstream_sha
                    or not (data["frozen"] or data.get("runtime_layout") == "official-embedded")
                    or data["platform_count"] < 3
                    or action == "--self-test"
                    and data.get("passed") is not True
                ):
                    raise ValueError("Health contract mismatch")
            except (ValueError, KeyError, TypeError) as exc:
                from .update_contracts import UpdateError

                raise UpdateError("UPDATE_HEALTH", "候选内核自检结果与签名清单不一致。") from exc
