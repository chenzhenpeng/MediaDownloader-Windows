"""Validate/select a prepared experimental environment, without touching app settings."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from media_downloader.official_environments import OfficialEnvironments  # noqa: E402
from media_downloader.official_paths import candidate_python  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = OfficialEnvironments(args.root)
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=True)
    if output.is_relative_to(store.directory(args.id)):
        raise ValueError("Probe output must be outside the candidate environment")

    def probe(directory):
        completed = subprocess.run(
            [
                str(candidate_python(directory)),
                "-B",
                "-I",
                str(ROOT / "scripts/probe_official_parsehub.py"),
                "--wheel",
                str(args.wheel.absolute()),
                "--output",
                str(output),
            ],
            capture_output=True,
            timeout=55,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if completed.returncode:
            # Avoid propagating arbitrary dependency output into application logs.
            raise ValueError("Official package compatibility probe failed")
        return json.loads((output / "report.json").read_text(encoding="utf-8"))

    # Some upstream dependencies populate local data caches on first import.
    # Prepare those before taking the immutable candidate inventory.
    probe(store.directory(args.id))
    store.validate(args.id, version=args.version, wheel_hash=args.sha256, probe=probe)
    before = store.snapshot()
    selected = store.select(args.id, expected_generation=before["generation"])
    assert store.resolve() == store.directory(args.id)
    assert OfficialEnvironments(args.root).resolve() == store.directory(args.id)
    summary = {
        "selection": selected,
        "resolve_after_restart": True,
        "production_enabled": False,
        "runtime_base": "embedded"
        if (store.directory(args.id) / "python.exe").is_file()
        else "development venv",
    }
    (output / "environment-selection.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
