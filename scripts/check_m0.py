"""Run frozen artifact checks with an intentionally stripped search PATH."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import time
from ctypes import wintypes as w
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = "m0"


class Memory(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("faults", w.DWORD)] + [
        (name, ctypes.c_size_t)
        for name in (
            "peak_working_set",
            "working_set",
            "peak_paged_pool",
            "paged_pool",
            "peak_nonpaged_pool",
            "nonpaged_pool",
            "pagefile",
            "peak_pagefile",
        )
    ]


def run(argv, name, env, timeout=90):
    start = time.monotonic()
    stdout = ROOT / ".local" / STAGE / f"{name}.stdout"
    stderr = ROOT / ".local" / STAGE / f"{name}.stderr"
    stdout.parent.mkdir(parents=True, exist_ok=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(Memory), w.DWORD]
    peak = 0
    with stdout.open("wb") as out, stderr.open("wb") as err:
        process = subprocess.Popen(argv, env=env, stdout=out, stderr=err, creationflags=0x08000000)
        handle = kernel.OpenProcess(0x0400 | 0x0010, False, process.pid)
        try:
            while process.poll() is None:
                if time.monotonic() - start > timeout:
                    process.kill()
                    process.wait()
                    raise TimeoutError(name)
                info = Memory()
                info.cb = ctypes.sizeof(info)
                if handle and psapi.GetProcessMemoryInfo(handle, ctypes.byref(info), info.cb):
                    peak = max(peak, info.peak_working_set)
                time.sleep(0.05)
        finally:
            if handle:
                kernel.CloseHandle(handle)
    if process.returncode:
        raise RuntimeError(f"{name} exited {process.returncode}; see {stderr}")
    return {
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "peak_process_working_set_mib": round(peak / 2**20, 2),
        "stdout": str(stdout.relative_to(ROOT)),
        "stderr": str(stderr.relative_to(ROOT)),
    }


def main():
    global STAGE
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--milestone",
        choices=[
            "m0",
            "m1",
            "m2",
            "m3",
            "m4",
            "ui",
            "naming",
            "polish",
            "platforms",
            "kuaishou",
            "review",
            "localized",
        ],
        default="m0",
    )
    STAGE = parser.parse_args().milestone
    engine = ROOT / "dist" / STAGE / "media-engine"
    ui = ROOT / "dist" / STAGE / "MediaDownloader" / "MediaDownloader.exe"
    env = dict(os.environ)
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env.pop("MEDIA_DOWNLOADER_YTDLP", None)
    env["PYTHONUTF8"] = "1"
    env["MEDIA_DOWNLOADER_DATA_DIR"] = str(ROOT / ".local" / STAGE / "packaged-app-data")
    report = {"scope": "current Windows host; stripped PATH, not a clean VM", "checks": {}}
    report["checks"]["engine_start"] = run(
        [str(engine / "media-engine.exe"), "--describe"], "engine-start", env
    )
    report["checks"]["engine_self_test"] = run(
        [
            str(engine / "media-engine.exe"),
            "--self-test",
            "--output",
            str(ROOT / ".local" / STAGE / "frozen-self-test"),
        ],
        "engine-self-test",
        env,
    )
    # A synthetic E2 tests selection and version isolation, not an upstream upgrade.
    fingerprint = hashlib.sha256((engine / "media-engine.exe").read_bytes()).hexdigest()[:8]
    alternate = ROOT / "dist" / STAGE / f"media-engine-e2-{fingerprint}"
    if not alternate.exists():
        shutil.copytree(engine, alternate, copy_function=os.link)
        manifest = json.loads((alternate / "engine.json").read_text(encoding="utf-8"))
        (alternate / "engine.json").unlink()  # break only the manifest hardlink before writing E2
        manifest["engine_version"] = manifest["engine_version"] + "-e2"
        (alternate / "engine.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for label, directory in (("e1", engine), ("e2", alternate)):
        screenshot = ROOT / ".local" / STAGE / f"frozen-ui-{label}.png"
        report["checks"][f"ui_with_{label}"] = run(
            [str(ui), "--engine-dir", str(directory), "--smoke-test", str(screenshot)], f"ui-{label}", env
        )
        evidence = json.loads(screenshot.with_suffix(".json").read_text(encoding="utf-8"))
        assert evidence["ui_frozen"] and evidence["engine"]["frozen"]
        assert (
            evidence["engine"]["engine_version"]
            == json.loads((directory / "engine.json").read_text())["engine_version"]
        )
        report["checks"][f"ui_with_{label}"]["evidence"] = evidence
    report["notes"] = [
        "Memory measures only the named process, not aggregate descendants.",
        "E2 has identical parser code and synthetic version metadata.",
        "This is not signed update or clean-machine acceptance.",
    ]
    path = ROOT / "review" / f"{STAGE}-packaged-checks.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # Hosted Windows runners may still use cp1252 for redirected stdout.
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
