"""One unsigned build path for contributors, PR validation and application releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments, cwd=ROOT):
    subprocess.run([str(arg) for arg in arguments], cwd=cwd, check=True)


def script(name, *arguments):
    run(sys.executable, ROOT / "scripts" / name, *arguments)


def new_work_directory(path):
    path = path.resolve()
    # No automatic cleanup or adoption of an existing partially built environment.
    if not any(path.is_relative_to(ROOT / parent) for parent in (".local", "build", "dist")):
        raise ValueError("Build work directory must be inside .local, build or dist")
    path.mkdir(parents=True, exist_ok=False)
    return path


def compiler_path():
    config = json.loads((ROOT / "packaging/windows/toolchain.json").read_bytes())
    compiler = ROOT / ".cache/installer-tools/InnoSetup7/ISCC.exe"
    if compiler.is_file():
        with compiler.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != config["iscc_sha256"]:
                raise ValueError("Cached compiler does not match pinned toolchain")
    else:
        script("fetch_installer_toolchain.py")
    return compiler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("components", "app", "installer"), default="installer")
    parser.add_argument("--components", type=Path, help="Reuse an accepted complete component bundle")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--sevenzip", type=Path)
    parser.add_argument("--qa", action="store_true", help="Also build the separate QA installer")
    parser.add_argument("--worker-version", default="0.3.0")
    parser.add_argument("--runtime-version", default="1.0.0")
    parser.add_argument("--tools-version", default="1.0.0")
    args = parser.parse_args()
    if sys.platform != "win32" or struct.calcsize("P") != 8 or sys.version_info[:2] != (3, 12):
        raise RuntimeError("Build on Windows with x64 Python 3.12")
    dotnet = ROOT / ".cache/dotnet/dotnet.exe"
    dotnet = str(dotnet) if dotnet.is_file() else shutil.which("dotnet")
    if args.stage != "components" and not dotnet:
        raise RuntimeError("Install the .NET SDK pinned in native/global.json")
    if args.stage != "components":
        run(dotnet, "--version", cwd=ROOT / "native")
    sevenzip = str(args.sevenzip.resolve(strict=True)) if args.sevenzip else shutil.which("7z")
    if not args.components and not sevenzip:
        raise RuntimeError("Install 7-Zip and add 7z to PATH, or pass --sevenzip")
    bundle = args.components.resolve(strict=True) if args.components else None
    work = new_work_directory(args.work_dir or ROOT / ".local/b" / uuid.uuid4().hex[:8])
    if bundle is None:
        script("fetch_media_tools.py", "--output", work / "tools", "--sevenzip", sevenzip, "--ffmpeg-only")
        tools, notices = work / "official-tools", work / "notices"
        tools.mkdir()
        notices.mkdir()
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            shutil.copy2(work / "tools/ffmpeg/bin" / name, tools / name)
        for source, target in (("LICENSE", "FFmpeg-LICENSE"), ("README.txt", "FFmpeg-README.txt")):
            shutil.copy2(work / "tools/ffmpeg" / source, notices / target)
        script(
            "build_official_runtime.py",
            "--output",
            work / "seed",
            "--version",
            "build-seed",
            "--seed-only",
            "--tools",
            tools,
        )
        bundle = work / "bundle"
        script(
            "build_component_bundle.py",
            "--seed",
            work / "seed",
            "--output",
            bundle,
            "--worker-version",
            args.worker_version,
            "--runtime-version",
            args.runtime_version,
            "--tools-version",
            args.tools_version,
        )
    script("check_official_contract.py", "--bundle", bundle, "--output", work / "official-contract.json")
    script("check_component_update.py", "--bundle", bundle, "--root", work / "update-acceptance")
    if args.stage != "components":
        # Match build_native.py's package directory and its --no-restore publish.
        os.environ.update(
            DOTNET_CLI_HOME=str(ROOT / ".cache/dotnet-home"),
            NUGET_PACKAGES=str(ROOT / ".cache/nuget/packages"),
            DOTNET_CLI_TELEMETRY_OPTOUT="1",
        )
        run(
            dotnet,
            "restore",
            ROOT / "native/MediaDownloader/MediaDownloader.csproj",
            "--locked-mode",
            "-p:Platform=x64",
            "--packages",
            ROOT / ".cache/nuget/packages",
            cwd=ROOT / "native",
        )
        script("build_native.py", "--engine-dir", bundle)
    if args.stage == "installer":
        compiler = compiler_path()
        script("build_installer.py", "--compiler", compiler)
        if args.qa:
            script("build_installer.py", "--compiler", compiler, "--qa")
    report = {
        "passed": True,
        "stage": args.stage,
        "bundle": str(bundle),
        "official_contract": str(work / "official-contract.json"),
        "application": "dist/native/MediaDownloader" if args.stage != "components" else None,
    }
    (work / "build-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
