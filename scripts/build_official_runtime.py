"""Build the separately versioned embedded runtime from hash-locked binary artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from dataclasses import asdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from media_downloader import PROTOCOL  # noqa: E402
from media_downloader.engine import resolve_engine  # noqa: E402
from media_downloader.engine_health import probe_engine  # noqa: E402
from media_downloader.official_packages import check_latest, download_wheel, inspect_wheel  # noqa: E402
from media_downloader.update_archive import no_reparse, safe_relative  # noqa: E402


def build(output, version, tools, *, seed_only=False):
    no_reparse(output)
    if output.exists():
        raise ValueError("Official runtime output must be a new directory")
    python = json.loads((ROOT / "packaging/official-python.json").read_bytes())
    lock = ROOT / "packaging/official-runtime.lock"
    cache = ROOT / ".cache/official-runtime"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / ("python-" + python["version"] + ".zip")
    if not archive.exists():
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", python["url"]) as response, archive.open("xb") as stream:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    stream.write(chunk)
                    if stream.tell() > 30 * 1024**2:
                        raise ValueError("Oversize Python archive")
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != python["sha256"]:
            raise ValueError("Pinned Python archive hash mismatch")
    output.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        if len(bundle.infolist()) > 1000 or sum(i.file_size for i in bundle.infolist()) > 100 * 1024**2:
            raise ValueError("Invalid Python archive inventory")
        for info in bundle.infolist():
            parts = safe_relative(info.filename)
            if info.is_dir():
                continue
            target = output.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(bundle.read(info))
    paths = list(output.glob("python*._pth"))
    if len(paths) != 1:
        raise ValueError("Ambiguous Python embedded layout")
    paths[0].write_text(paths[0].stem + ".zip\n.\nLib/site-packages\napp\nimport site\n", encoding="utf-8")
    # Upstream launches `python -m yt_dlp` itself. A sourceless startup module
    # keeps those children from writing bytecode into the signed runtime too.
    startup = cache / "sitecustomize.py"
    startup.write_text("import sys\nsys.dont_write_bytecode = True\n", encoding="utf-8")
    subprocess.run(
        [
            str(output / "python.exe"),
            "-B",
            "-I",
            "-c",
            "import py_compile,sys;py_compile.compile(sys.argv[1],cfile=sys.argv[2],"
            "dfile='sitecustomize.py',doraise=True)",
            str(startup),
            str(output / "sitecustomize.pyc"),
        ],
        check=True,
        timeout=30,
    )
    subprocess.run(
        [
            "uv",
            "--cache-dir",
            str(ROOT / ".cache/uv-official-production"),
            "pip",
            "install",
            "--python",
            str(output / "python.exe"),
            "--target",
            str(output / "Lib/site-packages"),
            "--only-binary",
            ":all:",
            "--no-binary",
            "signerpy",
            "--require-hashes",
            "--default-index",
            "https://pypi.org/simple",
            "-r",
            str(lock),
        ],
        check=True,
        timeout=300,
    )
    command = (
        "import importlib.metadata as m,json;from packaging.markers import default_environment;"
        "print(json.dumps({'dependencies':{d.metadata['Name']:d.version for d in m.distributions()},"
        "'marker_environment':default_environment()}))"
    )
    contract = json.loads(
        subprocess.check_output(
            [str(output / "python.exe"), "-B", "-I", "-c", command],
            text=True,
            timeout=30,
            creationflags=0x08000000,
        )
    )
    contract.update(
        adapter_abi=1,
        python=python["version"],
        extras={
            "yt-dlp": ["default"],
            "httpx": ["socks"],
            "python-slugify": ["unidecode"],
        },
    )
    wheel = check_latest()
    if wheel.version != contract["dependencies"].get("parsehub"):
        raise ValueError("Upstream advanced; review and refresh the dependency lock first")
    original = cache / wheel.filename
    if not original.exists():
        download_wheel(wheel, original)
    inventory = inspect_wheel(original, wheel, contract)
    for name, digest in inventory.items():
        if name.endswith(".dist-info/RECORD"):
            continue  # uv legitimately regenerates RECORD; source bytes remain unchanged.
        installed = output / "Lib/site-packages" / name
        if not installed.is_file() or hashlib.sha256(installed.read_bytes()).hexdigest() != digest:
            raise ValueError("Installed ParseHub differs from official wheel")
    shutil.copytree(
        ROOT / "src/media_downloader",
        output / "app/media_downloader",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (output / "worker_entry.py").write_text(
        "from media_downloader.official_worker import main\nraise SystemExit(main())\n",
        encoding="utf-8",
    )
    tool_lock = json.loads((ROOT / "packaging/media-tools-lock.json").read_bytes())
    (output / "tools").mkdir()
    for name in ("ffmpeg", "ffprobe"):
        source = tools / (name + ".exe")
        expected = tool_lock["ffmpeg"][name + "_sha256"]
        with source.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("Media tool differs from pinned artifact")
        shutil.copy2(source, output / "tools" / source.name)
    runtime_id = (
        "rt1-"
        + hashlib.sha256(
            lock.read_bytes() + json.dumps(python, sort_keys=True).encode() + b"official-adapter-1"
        ).hexdigest()[:24]
    )
    descriptor = {
        "layout": "official-embedded",
        "source_kind": "pypi-wheel",
        "patchset": "none-official-wheel",
        "component": "engine",
        "protocol": PROTOCOL,
        "target": "windows-x86_64",
        "engine_version": version,
        "runtime_id": runtime_id,
        "upstream_sha": wheel.sha256,
        "parsehub_version": wheel.version,
        "parser_component_version": wheel.version,
        "python": python["version"],
        "official_package_runtime": contract,
        "official_wheel": asdict(wheel),
        "yt-dlp": contract["dependencies"]["yt-dlp"],
        "tools": {name: {"version": tool_lock["ffmpeg"]["version"]} for name in ("ffmpeg", "ffprobe")},
    }
    (output / "engine.json").write_text(json.dumps(descriptor, indent=2), encoding="utf-8")
    (output / "upstream").mkdir()
    shutil.copy2(original, output / "upstream" / wheel.filename)
    notices = output / "notices"
    notices.mkdir()
    # Wheel license and dependency notices are retained in each installed dist-info.
    for name in ("FFmpeg-LICENSE", "FFmpeg-README.txt"):
        source = tools.parent / "notices" / name
        if not source.is_file():
            raise ValueError("Required FFmpeg redistribution notice is missing")
        shutil.copy2(source, notices / name)
    if not seed_only:
        probe_engine(resolve_engine(output))
    print(
        json.dumps(
            {
                "runtime": str(output),
                "version": version,
                "parsehub": wheel.version,
                "python": python["version"],
                "unmodified_wheel_verified": True,
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--version", required=True)
    parser.add_argument("--tools", required=True, type=Path)
    args = parser.parse_args()
    build(args.output.absolute(), args.version, args.tools.absolute(), seed_only=args.seed_only)


if __name__ == "__main__":
    main()
