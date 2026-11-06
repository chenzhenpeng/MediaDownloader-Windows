"""Split an authenticated build seed into independently releasable components."""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from media_downloader import PROTOCOL  # noqa: E402
from media_downloader.engine import resolve_engine  # noqa: E402
from media_downloader.engine_health import probe_engine  # noqa: E402
from media_downloader.official_packages import OfficialWheel, extract_wheel  # noqa: E402

# Worker import closure; deliberately excludes UI, database service and updater.
WORKER_MODULES = (
    "__init__",
    "official_worker",
    "official_adapter",
    "official_bridge",
    "worker",
    "engine_server",
    "contracts",
    "errors",
    "network",
    "progress",
    "media_paths",
    "platforms",
    "task_files",
    "artwork",
    "media_validation",
    "hls_transfer",
    "diagnostics",
    "windows",
)


def write(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def build(seed, output, worker_version="0.3.0", runtime_version="1.0.0", tools_version="1.0.0"):
    if output.exists():
        raise ValueError("Bundle output must be new")
    metadata = json.loads((seed / "engine.json").read_bytes())
    contract = metadata["official_package_runtime"]
    wheel = OfficialWheel(**metadata["official_wheel"])
    original = seed / "upstream" / wheel.filename
    output.mkdir(parents=True)
    # Native DLL dependency loaders still have path limits, especially with Unicode.
    # Logical names stay in metadata; short physical paths leave room for vendor DLL names.
    roots = {
        kind: output / "c" / slot
        for kind, slot in {"worker": "w", "python-runtime": "p", "parsehub": "h", "media-tools": "t"}.items()
    }
    for directory in roots.values():
        directory.mkdir(parents=True)
    python = roots["python-runtime"]
    for source in seed.iterdir():
        if source.name in {
            "app",
            "tools",
            "upstream",
            "notices",
            "engine.json",
            "worker_entry.py",
            "files.json",
            "healthy.json",
        }:
            continue
        if source.is_dir():
            shutil.copytree(source, python / source.name)
        else:
            shutil.copy2(source, python / source.name)
    site = python / "Lib/site-packages"
    for directory in [site / "parsehub", *site.glob("parsehub-*.dist-info")]:
        if directory.exists():
            if not directory.resolve().is_relative_to(python.resolve()):
                raise ValueError("Unsafe seed package directory")
            shutil.rmtree(directory)
    for pth in python.glob("python*._pth"):
        pth.write_text(pth.stem + ".zip\n.\nLib/site-packages\nimport site\n", encoding="utf-8")
    environment = {k: v for k, v in contract.items()}
    environment["dependencies"] = {
        k: v for k, v in contract["dependencies"].items() if k.lower() != "parsehub"
    }
    write(
        python / "component.json",
        {
            "schema": 1,
            "kind": "python-runtime",
            "version": runtime_version,
            "target": "windows-x86_64",
            "abi": 1,
            "python": contract["python"],
            "contract": environment,
            "identity": "rt1-"
            + hashlib.sha256((ROOT / "packaging/official-runtime.lock").read_bytes()).hexdigest()[:24],
        },
    )
    parser = roots["parsehub"]
    extract_wheel(original, wheel, environment, parser / "python")
    shutil.copy2(original, parser / wheel.filename)
    write(
        parser / "component.json",
        {
            "schema": 1,
            "kind": "parsehub",
            "version": wheel.version,
            "target": "windows-x86_64",
            "wheel": metadata["official_wheel"],
        },
    )
    worker = roots["worker"]
    app = worker / "app/media_downloader"
    app.mkdir(parents=True)
    for name in WORKER_MODULES:
        source = ROOT / "src/media_downloader" / (name + ".py")
        if not source.is_file():
            raise ValueError("Missing worker module: " + name)
        shutil.copy2(source, app / source.name)
    (worker / "worker_entry.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0,str(Path(__file__).resolve().parent/'app'))\n"
        "from media_downloader.official_worker import main\nraise SystemExit(main())\n",
        encoding="utf-8",
    )
    write(
        worker / "component.json",
        {
            "schema": 1,
            "kind": "worker",
            "version": worker_version,
            "target": "windows-x86_64",
            "protocol": PROTOCOL,
            "requires": {
                "environment_abi": 1,
                "python": ">=3.13,<3.14",
                "parsehub": ">=2.4,<3",
                "media_tools": ">=1,<2",
            },
        },
    )
    tools = roots["media-tools"]
    files = {}
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        shutil.copy2(seed / "tools" / name, tools / name)
        files[name] = hashlib.sha256((tools / name).read_bytes()).hexdigest()
    shutil.copytree(seed / "notices", tools / "notices")
    write(
        tools / "component.json",
        {
            "schema": 1,
            "kind": "media-tools",
            "version": tools_version,
            "target": "windows-x86_64",
            "files": files,
            "versions": metadata["tools"],
        },
    )
    write(
        output / "profile.json",
        {
            "schema": 1,
            "components": {
                kind: directory.relative_to(output).as_posix() for kind, directory in roots.items()
            },
        },
    )
    engine = resolve_engine(output)
    probe_engine(engine)
    print(
        json.dumps(
            {
                "passed": True,
                "components": engine.component_versions,
                "worker_files": len(list(app.glob("*.py"))),
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker-version", default="0.3.0")
    parser.add_argument("--runtime-version", default="1.0.0")
    parser.add_argument("--tools-version", default="1.0.0")
    args = parser.parse_args()
    build(
        args.seed.resolve(),
        args.output.resolve(),
        args.worker_version,
        args.runtime_version,
        args.tools_version,
    )
