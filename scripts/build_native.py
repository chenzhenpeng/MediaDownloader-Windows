"""Build the unpackaged native preview without replacing the existing Qt package."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist/native/MediaDownloader"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-dir", type=Path, default=ROOT / "dist/localized/media-engine")
    parser.add_argument(
        "--reuse-backend", action="store_true", help="UI-only rebuild after a verified backend build"
    )
    args = parser.parse_args()
    subprocess.run([sys.executable, str(ROOT / "scripts/build_app_icon.py")], cwd=ROOT, check=True)
    source = args.engine_dir.resolve()
    if not source.is_dir():
        raise ValueError("Engine source directory does not exist")
    env = dict(
        os.environ,
        DOTNET_CLI_HOME=str(ROOT / ".cache/dotnet-home"),
        NUGET_PACKAGES=str(ROOT / ".cache/nuget/packages"),
        DOTNET_CLI_TELEMETRY_OPTOUT="1",
        DOTNET_GENERATE_ASPNET_CERTIFICATE="false",
        PYINSTALLER_CONFIG_DIR=str(ROOT / ".cache/pyinstaller"),
    )
    # Always publish to an empty generated directory: an incremental copy keeps
    # removed SDK components and old Python dependencies in the installer.
    target = OUT.resolve()
    if not target.is_relative_to((ROOT / "dist/native").resolve()) or source.is_relative_to(target):
        raise ValueError("Unsafe or overlapping native output directory")
    if target.exists():
        shutil.rmtree(target)
    OUT.mkdir(parents=True)
    for notice in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / notice, OUT / notice)
    dotnet = ROOT / ".cache/dotnet/dotnet.exe"
    sdk = str(dotnet) if dotnet.is_file() else shutil.which("dotnet")
    if not sdk:
        raise RuntimeError("Install the pinned .NET SDK before building the native application")
    subprocess.run(
        [
            sdk,
            "publish",
            str(ROOT / "native/MediaDownloader/MediaDownloader.csproj"),
            "--no-restore",
            "-c",
            "Release",
            "-p:Platform=x64",
            "-o",
            str(OUT),
        ],
        cwd=ROOT / "native",
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
        "PySide6.QtNetwork",
        "numpy",
        "cv2",
        "PIL",
        "yt_dlp",
        "pytest",
    ]:
        command += ["--exclude-module", module]
    if not args.reuse_backend:
        subprocess.run(command + [str(entry)], cwd=ROOT, env=env, check=True)
    elif not (ROOT / "build/native-backend/MediaBackend/MediaBackend.exe").is_file():
        raise ValueError("No built backend to reuse")
    # QtCore supports scheduler signals/processes; no Qt GUI or software OpenGL
    # is used by the stdio backend. PyInstaller's generic Qt hook adds this DLL.
    software_gl = ROOT / "build/native-backend/MediaBackend/_internal/PySide6/opengl32sw.dll"
    software_gl.unlink(missing_ok=True)
    shutil.copytree(ROOT / "build/native-backend/MediaBackend", OUT / "backend", dirs_exist_ok=True)
    target = (OUT / "engine").resolve()
    if source != target:
        if not target.is_relative_to(ROOT.resolve() / "dist"):
            raise ValueError("Engine destination escapes distribution directory")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
    print(OUT, flush=True)


if __name__ == "__main__":
    main()
