"""Run release SDK contracts in its actual embedded Python, never the dev venv."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from media_downloader.engine import resolve_engine  # noqa: E402
from media_downloader.engine_health import probe_engine  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = resolve_engine(args.bundle.resolve())
    probe_engine(engine)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
    }
    environment["PATH"] = (
        str(engine.components["media-tools"])
        + os.pathsep
        + str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            engine.program,
            "-B",
            "-I",
            str(ROOT / "qa/official/contracts.py"),
            "--bundle",
            str(args.bundle.resolve()),
            "--output",
            str(args.output.resolve()),
        ],
        cwd=args.bundle.resolve(),
        env=environment,
        check=True,
        timeout=180,
    )
    report = json.loads(args.output.read_bytes())
    if not report["passed"] or report["tests_run"] < 8:
        raise ValueError("Official SDK contract suite did not complete")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
