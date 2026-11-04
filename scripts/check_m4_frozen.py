"""Actual frozen UI E1 -> signed E2 -> E1, with one uninterrupted client process."""

import argparse
import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from release_engine import package_release

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT / "dist/m4/media-engine"
    candidate = output / "candidate-source"
    shutil.copytree(source, candidate, copy_function=os.link)
    descriptor = candidate / "engine.json"
    metadata = json.loads(descriptor.read_text(encoding="utf-8"))
    descriptor.unlink()  # Never mutate the baseline through a hardlink.
    metadata["engine_version"] += "-e2"
    descriptor.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    key = Ed25519PrivateKey.generate()  # Ephemeral QA key; never added to the distributed trust file.
    manifest = package_release(candidate, output / "feed", key, sequence=7)
    trust_file = output / "test-trust.json"
    trust_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "channel": "beta",
                "development_directory": "feed",
                "keys": {"local-test": base64.b64encode(key.public_key().public_bytes_raw()).decode()},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    environment = dict(
        os.environ,
        MEDIA_DOWNLOADER_DATA_DIR=str(output / "app-data"),
        PATH=str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"),
    )
    for name in ("VIRTUAL_ENV", "PYTHONPATH", "MEDIA_DOWNLOADER_YTDLP"):
        environment.pop(name, None)
    subprocess.run(
        [
            str(ROOT / "dist/m4/MediaDownloader/MediaDownloader.exe"),
            "--engine-dir",
            str(source),
            "--update-config",
            str(trust_file),
            "--update-smoke-test",
            str(output / "client-proof"),
        ],
        env=environment,
        check=True,
        timeout=260,
        creationflags=0x08000000,
    )
    report = json.loads((output / "client-proof/report.json").read_text(encoding="utf-8"))
    assert report["passed"] and report["client_frozen"] and report["same_client_pid"]
    assert report["highest_sequence"] == 7 and report["state"]["current"] == "bundled"
    report["signed_artifact"] = {k: manifest[k] for k in ("size_bytes", "sha256", "file_count", "sequence")}
    (ROOT / "review/m4-frozen-update.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
