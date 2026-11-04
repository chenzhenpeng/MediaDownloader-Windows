"""Build the unpackaged native preview without replacing the existing Qt package."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist/native/MediaDownloader"


def main():
    env = dict(
        os.environ,
        DOTNET_CLI_HOME=str(ROOT / ".cache/dotnet-home"),
        NUGET_PACKAGES=str(ROOT / ".cache/nuget/packages"),
        DOTNET_CLI_TELEMETRY_OPTOUT="1",
        DOTNET_GENERATE_ASPNET_CERTIFICATE="false",
        PYINSTALLER_CONFIG_DIR=str(ROOT / ".cache/pyinstaller"),
    )
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(ROOT / ".cache/dotnet/dotnet.exe"),
            "publish",
            "native/MediaDownloader/MediaDownloader.csproj",
            "--no-restore",
            "-c",
            "Release",
            "-p:Platform=x64",
            "-o",
            str(OUT),
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    native_bin = ROOT / "native/MediaDownloader/bin/x64/Release/net10.0-windows10.0.26100.0/win-x64"
    for resource in [native_bin / "MediaDownloader.pri", *native_bin.glob("*.xbf")]:
        shutil.copy2(resource, OUT / resource.name)
    entry = ROOT / "build/entries/native_backend.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        "from media_downloader.desktop_host import main\nraise SystemExit(main())\n", encoding="utf-8"
    )
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",
        "--noupx",
        "--name",
        "MediaBackend",
        "--paths",
        str(ROOT / "src"),
        "--distpath",
        str(ROOT / "build/native-backend"),
        "--workpath",
        str(ROOT / "build/native-pyinstaller"),
        "--specpath",
        str(ROOT / "build/specs"),
        "--add-data",
        str(ROOT / "packaging/update-trust.json") + ";.",
    ]
    for module in [
        "parsehub",
        "PySide6.QtWidgets",
        "PySide6.QtGui",
        "numpy",
        "cv2",
        "PIL",
        "yt_dlp",
        "pytest",
    ]:
        command += ["--exclude-module", module]
    subprocess.run(command + [str(entry)], cwd=ROOT, env=env, check=True)
    shutil.copytree(ROOT / "build/native-backend/MediaBackend", OUT / "backend", dirs_exist_ok=True)
    shutil.copytree(ROOT / "dist/localized/media-engine", OUT / "engine", dirs_exist_ok=True)
    print(OUT, flush=True)


if __name__ == "__main__":
    main()
