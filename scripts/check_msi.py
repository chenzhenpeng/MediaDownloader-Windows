"""Exercise the separately identified QA MSI without changing a user's installation."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import winreg
from pathlib import Path

from msi_inspect import inspect

ROOT = Path(__file__).resolve().parents[1]


def main():
    package = ROOT / "build/msi-qa/MediaDownloader-0.2.0-preview.5-win-x64-QA.msi"
    metadata = inspect(package)
    qa = ROOT / ".local/msi-qa" / str(time.time_ns())
    destination, data = qa / "程序目录", qa / "state"
    qa.mkdir(parents=True)
    installer = Path(os.environ["SystemRoot"]) / "System32/msiexec.exe"
    executable = destination / "versions/0.2.0-preview.5/MediaDownloader.exe"
    report = {"qa_directory": str(qa), "architecture": metadata}
    default_executable = (
        Path(os.environ["LOCALAPPDATA"])
        / "Programs/MediaDownloaderMSIQA/versions/0.2.0-preview.5/MediaDownloader.exe"
    )
    default_existed = default_executable.exists()

    def remembered_root():
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\MediaDownloaderMSIQA\Installer") as key:
            return Path(winreg.QueryValueEx(key, "InstallRoot")[0]).resolve()

    def run_msi(mode, target, log):
        # msiexec parses PROPERTY="value" itself rather than using the CRT's
        # argument quoting rules for a whole "PROPERTY=value" argument.
        command = (
            f'"{installer}" {mode} "{target}" /qn /norestart /l*v "{qa / log}" INSTALLFOLDER="{destination}"'
        )
        result = subprocess.run(
            command,
            timeout=240,
            check=False,
        )
        if result.returncode not in {0, 3010}:
            raise RuntimeError(f"MSI {mode} failed with {result.returncode}; see {qa / log}")

    def smoke(name):
        output = qa / f"{name}.json"
        subprocess.run(
            [
                str(executable),
                "--data-dir",
                str(data),
                "--smoke-report",
                str(output),
                "--smoke-page",
                "settings",
                "--smoke-settings-expanded",
                "true",
                "--smoke-cookie-fixture",
                "true",
            ],
            timeout=60,
            check=True,
        )
        value = json.loads(output.read_text(encoding="utf-8"))
        assert value["backend"]["client_version"] == "0.2.0.dev5"
        assert all(value["layout"]["checks"].values())
        assert "test_cookie=fixture" not in output.read_text(encoding="utf-8")
        return value

    installed = False
    try:
        run_msi("/i", package, "install.log")
        installed = True
        assert executable.is_file()
        first = smoke("installed-settings")
        assert sum(p["available"] for p in first["backend"]["platforms"]) == 24
        assert first["backend"]["update"]["configured"]
        assert remembered_root() == destination.resolve()
        report["installed_native_launch_and_cookie_reload"] = True
        sentinel = destination / "user-file-keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        database = data / "tasks.sqlite3"
        with sqlite3.connect(database) as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('msi_qa_marker', '\"keep\"')")
        run_msi("/fa", package, "repair.log")
        smoke("repaired-settings")
        assert remembered_root() == destination.resolve()
        if not default_existed:
            assert not default_executable.exists()
        report["repair_preserves_install_location"] = True
        assert sentinel.read_text(encoding="utf-8") == "preserve"
        report["repair_preserves_user_data"] = True
    finally:
        if installed:
            assert destination.resolve().is_relative_to(qa.resolve())
            run_msi("/x", metadata["product_code"], "uninstall.log")
    assert not executable.exists() and sentinel.is_file() and database.is_file()
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT value FROM settings WHERE key='msi_qa_marker'").fetchone()[0] == '"keep"'
    report["uninstall_preserves_user_files_and_data"] = True
    output = ROOT / "review/native/msi-acceptance.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
