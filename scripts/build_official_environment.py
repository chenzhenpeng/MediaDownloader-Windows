"""Offline experimental assembly; never installs Python or packages globally."""

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from media_downloader.update_archive import no_reparse, safe_relative  # noqa: E402


def build(archive: Path, expected_hash: str, requirements: Path, output: Path):
    no_reparse(output)
    if output.exists():
        raise ValueError("Candidate output already exists; use a new identifier")
    actual_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("Python archive digest mismatch")
    # Dependencies are resolved before assembly. No pip or online installer is
    # shipped inside the embedded runtime.
    output.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        if len(bundle.infolist()) > 1000 or sum(item.file_size for item in bundle.infolist()) > 100 * 1024**2:
            raise ValueError("Unexpected Python archive size")
        seen = set()
        for info in bundle.infolist():
            parts = safe_relative(info.filename)
            key = info.filename.casefold()
            if key in seen or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Duplicate or linked Python archive entry")
            seen.add(key)
            target = output.joinpath(*parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(info))
    paths = list(output.glob("python*._pth"))
    if len(paths) != 1 or not (output / "python.exe").is_file():
        raise ValueError("Unsupported embedded Python archive")
    standard_library = paths[0].stem + ".zip"
    if not (output / standard_library).is_file():
        raise ValueError("Embedded standard library missing")
    paths[0].write_text(f"{standard_library}\n.\nLib/site-packages\n", encoding="utf-8")
    subprocess.run(
        [
            "uv",
            "--cache-dir",
            str(ROOT / ".cache/uv-official"),
            "pip",
            "install",
            "--offline",
            "--python",
            str(ROOT / ".venv/Scripts/python.exe"),
            "--target",
            str(output / "Lib/site-packages"),
            "-r",
            str(requirements),
        ],
        check=True,
        timeout=180,
    )
    (output / "runtime-provenance.json").write_text(
        json.dumps(
            {
                "layout": "python-embed",
                "archive_sha256": actual_hash,
                "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
                "production_approved": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.archive, args.sha256, args.requirements, args.output.absolute())


if __name__ == "__main__":
    main()
