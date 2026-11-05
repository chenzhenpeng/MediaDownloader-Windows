"""Install/repair/uninstall in a workspace QA directory, preserving unknown files.

Uses a separate QA product identity and never uninstalls an entry pointing
outside this QA run.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import sqlite3
import subprocess
import time
import winreg
from pathlib import Path

from build_installer import machine

ROOT = Path(__file__).resolve().parents[1]
KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{B3EE607A-217F-4CBA-9037-A5C55D366932}_is1"
VERSION = "0.2.0-preview.14"


def installed():
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        ) as key:
            return {
                name: winreg.QueryValueEx(key, name)[0]
                for name in ("InstallLocation", "DisplayVersion", "UninstallString")
            }
    except FileNotFoundError:
        return None


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    if installed():
        raise RuntimeError("Product is already installed; refusing to alter the existing installation")
    qa = ROOT / ".local/installer-qa" / str(time.time_ns())
    destination, data = qa / "安装目录", qa / "state"
    qa.mkdir(parents=True)
    setup = ROOT / f"dist/release/MediaDownloader-{VERSION}-win-x64-QA-Setup.exe"
    assert machine(setup) == 0x8664
    inventory = json.loads((ROOT / f"dist/release/MediaDownloader-{VERSION}-QA-payload.json").read_text())
    report = {
        "qa_directory": str(qa),
        "release": VERSION,
        "setup_x64": True,
        "tested_without_admin": not bool(ctypes.windll.shell32.IsUserAnAdmin()),
        "uses_msi": False,
    }
    payload = destination / "versions" / VERSION
    executable = payload / "MediaDownloader.exe"

    def install(log):
        return subprocess.run(
            [
                str(setup),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/NOICONS",
                "/TASKS=",
                f"/DIR={destination}",
                f"/LOG={qa / log}",
            ],
            timeout=180,
            check=False,
        ).returncode

    def smoke(name):
        output = qa / f"{name}.json"
        subprocess.run(
            [str(executable), "--data-dir", str(data), "--smoke-report", str(output)], timeout=60, check=True
        )
        value = json.loads(output.read_text(encoding="utf-8"))
        assert value["native_ui"] == "WinUI 3"
        assert sum(p["available"] for p in value["backend"]["platforms"]) == 24
        return value

    def assert_owned():
        entry = installed()
        assert entry and Path(entry["InstallLocation"]).resolve() == destination.resolve()
        assert destination.resolve().is_relative_to(qa.resolve())
        return entry

    try:
        assert install("install.log") == 0
        entry = assert_owned()
        assert entry["DisplayVersion"] == VERSION
        assert machine(destination / "unins000.exe") == 0x8664
        report["uninstaller_x64"] = True
        for item in inventory:
            assert sha(payload / item["path"]) == item["sha256"], item["path"]
        report["installed_inventory_files"] = len(inventory)
        first = smoke("first-launch")
        assert first["backend"]["client_version"] == "0.2.0.dev14"
        report["installed_native_launch"] = True
        sentinel = destination / "user-created-keep.txt"
        sentinel.write_text("User-owned file: preserve during repair and uninstall", encoding="utf-8")
        database = data / "tasks.sqlite3"
        with sqlite3.connect(database) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 4
            report["database_schema"] = 4
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("installer_qa_preserve", '"keep"'))
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateMutexW(None, False, r"Local\MediaDownloader.InstallerQA.Running")
        assert handle
        try:
            assert install("running-app-block.log") != 0
            report["running_app_blocks_installer"] = True
        finally:
            kernel.CloseHandle(handle)
        assert install("repair.log") == 0
        assert_owned()
        assert sentinel.read_text(encoding="utf-8").startswith("User-owned")
        second = smoke("after-repair")
        assert second["backend"]["engine_version"] == first["backend"]["engine_version"]
        with sqlite3.connect(database) as db:
            assert (
                db.execute("SELECT value FROM settings WHERE key='installer_qa_preserve'").fetchone()[0]
                == '"keep"'
            )
        report["repair_preserves_data"] = True
    finally:
        entry = installed()
        if entry:
            assert_owned()
            uninstaller = destination / "unins000.exe"
            subprocess.run(
                [
                    str(uninstaller),
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    f"/LOG={qa / 'uninstall.log'}",
                ],
                timeout=90,
                check=True,
            )
            deadline = time.monotonic() + 20
            while installed() and time.monotonic() < deadline:
                time.sleep(0.25)
        assert installed() is None
    assert not executable.exists()
    assert sentinel.is_file() and database.is_file()
    with sqlite3.connect(database) as db:
        assert (
            db.execute("SELECT value FROM settings WHERE key='installer_qa_preserve'").fetchone()[0]
            == '"keep"'
        )
    report["uninstall_removes_program"] = True
    report["uninstall_preserves_unknown_file_and_data"] = True
    output = ROOT / "review/native/installer-acceptance.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
