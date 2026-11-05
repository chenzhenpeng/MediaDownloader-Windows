"""Bounded process preflight for the experimental official environment path."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from .official_paths import candidate_python
from .windows import ProcessJob

HANDSHAKE = """
import importlib.metadata, json, pathlib, sys
import parsehub
from parsehub import ParseHub
hub = ParseHub()
print(json.dumps({'version': importlib.metadata.version('parsehub'),
 'origin': str(pathlib.Path(parsehub.__file__).resolve()),
 'parsers': len(hub.parsers), 'bits': 64 if sys.maxsize > 2**32 else 32}))
"""


def preflight(directory: Path, *, timeout=30, cancelled=lambda: False):
    """No credentials or media requests; this is not the worker task handshake."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA"}
    }
    environment["PATH"] = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
    with tempfile.TemporaryDirectory(prefix="official-startup-") as temporary:
        root = Path(temporary)
        output, errors = root / "stdout", root / "stderr"
        with output.open("wb") as stdout, errors.open("wb") as stderr:
            process = subprocess.Popen(
                [str(candidate_python(directory)), "-B", "-I", "-c", HANDSHAKE],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            job = None
            try:
                job = ProcessJob(process.pid)
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    if cancelled():
                        raise InterruptedError("Official startup cancelled")
                    if time.monotonic() > deadline:
                        raise TimeoutError("Official startup timed out")
                    if output.stat().st_size + errors.stat().st_size > 1024 * 1024:
                        raise ValueError("Official startup output exceeded limit")
                    time.sleep(0.05)
                if process.returncode:
                    raise ValueError("Official environment could not start")
            finally:
                if job:
                    job.close()
                if process.poll() is None:
                    process.kill()
                process.wait()
        if output.stat().st_size > 64 * 1024:
            raise ValueError("Official startup report exceeded limit")
        report = json.loads(output.read_bytes())
        if (
            not Path(report["origin"]).is_relative_to(directory)
            or report["bits"] != 64
            or report["parsers"] < 1
        ):
            raise ValueError("Official startup identity mismatch")
        return report


def prepare_launch(store, *, check=preflight):
    """Reserve, preflight and mark ready; caller must eventually finish the lease.

    Cancellation releases the lease without quarantining a healthy environment.
    A failed preflight restores a healthy previous selection but never silently
    retries the user's media task.
    """
    lease = store.reserve_launch()
    if lease is None:
        return None
    try:
        report = check(lease["directory"])
        expected = store.version(lease["environment"])
        if report.get("version") != expected:
            raise ValueError("Official startup version mismatch")
    except InterruptedError:
        store.finish_launch(lease["token"])
        raise
    except Exception:
        store.finish_launch(lease["token"], startup_failed=True)
        raise
    store.launch_ready(lease["token"])
    return lease
