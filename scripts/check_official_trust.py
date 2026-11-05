"""Development trust proof. Ephemeral private key stays in memory; no publication."""

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from media_downloader.official_paths import candidate_python  # noqa: E402
from media_downloader.official_trust import VerifiedOfficialEnvironments  # noqa: E402
from media_downloader.update_contracts import Trust  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-runtime", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    trust = Trust("beta", {"development-proof": public})
    if args.root.exists():
        raise ValueError("Development trust proof requires a fresh root")
    store = VerifiedOfficialEnvironments(args.root, trust)
    identifier = "official-" + args.version.replace(".", "_")
    directory = store.directory(identifier)
    shutil.copytree(args.source_runtime, directory)
    manifest = {
        "schema": 1,
        "kind": "official-environment",
        "target": "windows-x86_64",
        "channel": "beta",
        "key_id": "development-proof",
        "sequence": 1,
        "version": args.version,
        "wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "files": json.loads(store._inventory(identifier)),
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    signature = key.sign(raw)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "environment.json").write_bytes(raw)
    (args.output / "environment.sig").write_bytes(signature)

    def probe(candidate):
        result = subprocess.run(
            [
                str(candidate_python(candidate)),
                "-B",
                "-I",
                str(ROOT / "scripts/probe_official_parsehub.py"),
                "--wheel",
                str(args.wheel.resolve()),
                "--output",
                str(args.output.resolve()),
            ],
            capture_output=True,
            timeout=55,
            creationflags=0x08000000,
        )
        if result.returncode:
            raise ValueError("Authenticated candidate compatibility failed")
        return json.loads((args.output / "report.json").read_text(encoding="utf-8"))

    store.admit(identifier, raw, signature, args.wheel, probe=probe)
    store.select(identifier, expected_generation=0)
    trust_file = store.root / "development-trust.json"
    trust_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "channel": "beta",
                "development_directory": ".",
                "keys": {"development-proof": base64.b64encode(public).decode()},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    assert store.resolve() == directory
    summary = {
        "signed_admission": True,
        "original_wheel_verified": True,
        "selected": store.snapshot(),
        "development_key_only": True,
        "production_enabled": False,
    }
    (args.output / "trust-check.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
