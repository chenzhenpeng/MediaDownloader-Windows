"""Explicit experimental launcher. Credentials travel over stdin, never argv."""

import argparse
import asyncio
import contextlib
import functools
import importlib.metadata
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experimental-official", action="store_true", required=True)
    parser.add_argument("--serve", action="store_true", required=True)
    parser.add_argument("--tools-directory", type=Path)
    parser.add_argument("--expected-parsehub-version")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "src"))
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="strict")
    if args.tools_directory:
        directory = args.tools_directory.resolve(strict=True)
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            if not (directory / name).is_file():
                raise ValueError("Media tool missing")
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    # Load the official package before accepting commands. No vendored path is
    # injected, and the default worker remains unchanged.
    import parsehub

    from media_downloader import worker
    from media_downloader.engine_server import serve
    from media_downloader.official_adapter import OfficialAdapter

    if not Path(parsehub.__file__).resolve().is_relative_to(Path(sys.executable).resolve().parent):
        raise ValueError("Official package is outside embedded runtime")
    if (
        args.expected_parsehub_version
        and importlib.metadata.version("parsehub") != args.expected_parsehub_version
    ):
        raise ValueError("Selected official package version mismatch")
    adapter = functools.partial(OfficialAdapter, experimental=True)
    execute = functools.partial(worker.execute, adapter_factory=adapter)
    with contextlib.redirect_stdout(sys.stderr):
        asyncio.run(serve(execute=execute))


if __name__ == "__main__":
    main()
