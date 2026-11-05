"""Build isolated M0 artifacts. Does not publish, sign, or install anything."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from media_downloader import ENGINE_VERSION, PROTOCOL, UPSTREAM_SHA, __version__  # noqa: E402
from media_downloader.parser_runtime import runtime_id  # noqa: E402

ARTIFACT_ROOT = ROOT / "dist" / "m0"


def build(name, entry, extra):
    log = ROOT / "build" / "logs" / f"{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--noupx",
        "--name",
        name,
        "--distpath",
        str(ARTIFACT_ROOT),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(ROOT / "build" / "specs"),
        "--paths",
        str(ROOT / "src"),
        *extra,
        str(entry),
    ]
    env = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(ROOT / ".cache" / "pyinstaller"))
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
    print(f"Built {name}: {time.monotonic() - started:.1f}s ({log.relative_to(ROOT)})", flush=True)


def baseline_report():
    (ROOT / "review").mkdir(parents=True, exist_ok=True)
    repository = ROOT / ".cache" / "upstream-baseline"
    if not repository.exists():
        subprocess.run(
            ["git", "clone", "--bare", "https://github.com/z-mio/ParseHub.git", str(repository)], check=True
        )
    actual = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", f"{UPSTREAM_SHA}^{{commit}}"], text=True
    ).strip()
    if actual != UPSTREAM_SHA:
        raise RuntimeError("Upstream SHA mismatch")
    entries = subprocess.check_output(
        ["git", "-C", str(repository), "ls-tree", "-r", "--name-only", UPSTREAM_SHA], text=True
    ).splitlines()
    differences = []
    for relative in entries:
        original = subprocess.check_output(
            ["git", "-C", str(repository), "show", f"{UPSTREAM_SHA}:{relative}"]
        )
        local = ROOT / "upstream-ParseHub" / relative
        if not local.exists() or local.read_bytes().replace(b"\r\n", b"\n").rstrip(b"\n") != original.replace(
            b"\r\n", b"\n"
        ).rstrip(b"\n"):
            differences.append(relative)
    lock = subprocess.check_output(["git", "-C", str(repository), "show", f"{UPSTREAM_SHA}:uv.lock"])
    lock_path = ROOT / ".cache" / "upstream-original.lock"
    lock_path.write_bytes(lock)
    report = {
        "upstream_sha": UPSTREAM_SHA,
        "tracked_files": len(entries),
        "upstream_lock_sha256": hashlib.sha256(lock).hexdigest(),
        "local_differences": differences,
        "note": "Original uv.lock retained in .cache; application uses root uv.lock with local patches.",
    }
    (ROOT / "review" / "upstream-baseline.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def main():
    global ARTIFACT_ROOT
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
    parser.add_argument("--engine-version", default=ENGINE_VERSION)
    parser.add_argument("--skip-client", action="store_true")
    parser.add_argument("--skip-engine", action="store_true")
    parser.add_argument("--skip-tools", action="store_true")
    parser.add_argument("--ffmpeg-dir", type=Path, default=Path(r"D:\Program Files\ffmpeg\bin"))
    parser.add_argument(
        "--ytdlp-exe", type=Path, help="Reviewed standalone yt-dlp, avoids a duplicate runtime"
    )
    args = parser.parse_args()
    ARTIFACT_ROOT = ROOT / "dist" / args.milestone
    baseline_report()
    entry_dir = ROOT / "build" / "entries"
    entry_dir.mkdir(parents=True, exist_ok=True)
    engine_entry = entry_dir / "engine_entry.py"
    engine_entry.write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "import media_downloader.worker as worker\n"
        "worker.ENGINE_VERSION = json.loads((Path(sys.executable).parent / 'engine.json')"
        ".read_text(encoding='utf-8'))['engine_version']\n"
        "raise SystemExit(worker.main())\n",
        encoding="utf-8",
    )
    yt_entry = entry_dir / "ytdlp_entry.py"
    yt_entry.write_text("from yt_dlp import main\nraise SystemExit(main())\n", encoding="utf-8")
    if args.ytdlp_exe:
        lock = json.loads((ROOT / "packaging/media-tools-lock.json").read_text(encoding="utf-8"))
        actual = hashlib.file_digest(args.ytdlp_exe.open("rb"), "sha256").hexdigest()
        if actual != lock["yt-dlp"]["sha256"]:
            raise ValueError("Standalone yt-dlp does not match the reviewed tool lock")
        for name in ("ffmpeg", "ffprobe"):
            actual = hashlib.file_digest((args.ffmpeg_dir / f"{name}.exe").open("rb"), "sha256").hexdigest()
            if actual != lock["ffmpeg"][f"{name}_sha256"]:
                raise ValueError(f"{name} does not match the reviewed slim tool lock")
    elif not args.skip_tools:
        build("yt-dlp", yt_entry, ["--console", "--collect-all", "yt_dlp", "--exclude-module", "PySide6"])
    elif not (ARTIFACT_ROOT / "yt-dlp").exists():
        shutil.copytree(ROOT / "dist/m0/yt-dlp", ARTIFACT_ROOT / "yt-dlp")
    if not args.skip_engine:
        build(
            "media-engine",
            engine_entry,
            [
                "--console",
                "--collect-submodules",
                "parsehub",
                "--collect-data",
                "urlextract",
                "--collect-data",
                "SignerPy",
                "--copy-metadata",
                "parsehub",
                "--copy-metadata",
                "yt-dlp",
                "--exclude-module",
                "PySide6",
                "--exclude-module",
                "pytest",
                "--exclude-module",
                "tkinter",
                "--exclude-module",
                "cv2",
                "--exclude-module",
                "numpy",
            ],
        )
    if not args.skip_client:
        from PySide6.QtCore import QLibraryInfo

        translation = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) / "qtbase_zh_CN.qm"
        if not translation.is_file():
            raise FileNotFoundError(translation)
        subprocess.run([sys.executable, str(ROOT / "scripts/build_app_icon.py")], check=True)
        build(
            "MediaDownloader",
            ROOT / "packaging" / "client_entry.py",
            [
                "--windowed",
                "--icon",
                str(ROOT / "build/icons/media-downloader.ico"),
                "--add-data",
                str(ROOT / "packaging/update-trust.json") + os.pathsep + ".",
                "--add-data",
                str(translation) + os.pathsep + "translations",
                "--exclude-module",
                "parsehub",
                "--exclude-module",
                "cv2",
                "--exclude-module",
                "numpy",
                "--exclude-module",
                "pytest",
                "--exclude-module",
                "tkinter",
            ],
        )
    engine_dir = ARTIFACT_ROOT / "media-engine"
    if args.skip_engine:
        # A client-only rebuild must not modify an engine being exercised elsewhere.
        descriptor = json.loads((engine_dir / "engine.json").read_text(encoding="utf-8"))
        print(json.dumps({"engine_dir": str(engine_dir), "engine_reused": True}), flush=True)
        return
    tool_dir = engine_dir / "tools"
    tool_dir.mkdir(exist_ok=True)
    if args.ytdlp_exe:
        shutil.copy2(args.ytdlp_exe, tool_dir / "yt-dlp.exe")
    else:
        shutil.copytree(ARTIFACT_ROOT / "yt-dlp", tool_dir, dirs_exist_ok=True)
    tool_metadata = {}
    for name in ("ffmpeg", "ffprobe"):
        path = args.ffmpeg_dir / f"{name}.exe"
        if not path.is_file():
            raise FileNotFoundError(path)
        shutil.copy2(path, tool_dir / path.name)
        tool_metadata[name] = {
            "version": subprocess.check_output([str(path), "-version"], text=True).splitlines()[0],
            "sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
        }
    for library in args.ffmpeg_dir.glob("*.dll"):
        shutil.copy2(library, tool_dir / library.name)
    notices = engine_dir / "notices"
    notices.mkdir(exist_ok=True)
    shutil.copy2(ROOT / "upstream-ParseHub" / "LICENSE", notices / "ParseHub-LICENSE")
    shutil.copy2(args.ffmpeg_dir.parent / "LICENSE", notices / "FFmpeg-LICENSE")
    shutil.copy2(args.ffmpeg_dir.parent / "README.txt", notices / "FFmpeg-README.txt")
    descriptor = {
        "runtime_id": runtime_id(ROOT / "uv.lock"),
        "parser_adapter_abi": 1,
        "parser_component_version": args.engine_version,
        "parsehub_version": importlib.metadata.version("parsehub"),
        "protocol": PROTOCOL,
        "target": "windows-x86_64",
        "engine_version": args.engine_version,
        "upstream_sha": UPSTREAM_SHA,
        "patchset": "sha256-"
        + hashlib.sha256((ROOT / "patches/parsehub/patchset.json").read_bytes()).hexdigest()[:12],
        "app_version": __version__,
        "python": sys.version.split()[0],
        "yt-dlp": importlib.metadata.version("yt-dlp"),
        "tools": tool_metadata,
        "distribution": f"{args.milestone.upper()} local validation only; unsigned",
    }
    (engine_dir / "engine.json").write_text(
        json.dumps(descriptor, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    files = list(engine_dir.rglob("*"))
    descriptor["artifact_size_bytes"] = sum(p.stat().st_size for p in files if p.is_file())
    (ROOT / "build" / f"{args.milestone}-build.json").write_text(
        json.dumps(descriptor, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {"engine_dir": str(engine_dir), "size_mib": round(descriptor["artifact_size_bytes"] / 2**20, 1)},
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
