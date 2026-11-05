"""Build only reviewed ParseHub sources, bound to an existing signed runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tomllib
from pathlib import Path

from media_downloader import PROTOCOL, UPSTREAM_SHA
from media_downloader.parser_runtime import runtime_id
from media_downloader.update_contracts import load_trust, verify_manifest

ROOT = Path(__file__).resolve().parents[1]


def build(output, version, runtime_manifest):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}", version):
        raise ValueError("Invalid component version")
    identifier = runtime_id(ROOT / "uv.lock")
    if (
        runtime_manifest.get("component", "engine") != "engine"
        or runtime_manifest.get("runtime_id") != identifier
    ):
        raise ValueError("Dependency/runtime contract changed: publish an updated client runtime first")
    output.mkdir(parents=True, exist_ok=False)
    package = ROOT / "upstream-ParseHub/src/parsehub"
    target = output / "python/parsehub"
    target.mkdir(parents=True)
    for file in package.rglob("*"):
        if "__pycache__" in file.parts or file.suffix in {".pyc", ".pyo"}:
            continue
        if file.is_symlink():
            raise ValueError("Parser source contains a link")
        if file.is_file():
            destination = target / file.relative_to(package)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, destination)
    upstream = tomllib.loads((ROOT / "upstream-ParseHub/pyproject.toml").read_text(encoding="utf-8"))
    parser_version = upstream["project"]["version"]
    metadata = output / "python" / f"parsehub-{parser_version}.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: parsehub\nVersion: {parser_version}\nLicense: MIT\n", encoding="utf-8"
    )
    (output / "notices").mkdir()
    (output / "adapter").mkdir()
    shutil.copy2(ROOT / "src/media_downloader/adapter.py", output / "adapter/adapter.py")
    shutil.copy2(ROOT / "upstream-ParseHub/LICENSE", output / "notices/ParseHub-LICENSE")
    descriptor = {
        "protocol": PROTOCOL,
        "target": "windows-x86_64",
        "component": "parsehub",
        "adapter_abi": 1,
        "engine_version": version,
        "upstream_sha": UPSTREAM_SHA,
        "parsehub_version": parser_version,
        "patchset": "sha256-"
        + hashlib.sha256((ROOT / "patches/parsehub/patchset.json").read_bytes()).hexdigest()[:12],
        "requires_runtime_id": identifier,
    }
    (output / "engine.json").write_text(json.dumps(descriptor, indent=2), encoding="utf-8")
    return descriptor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--runtime-manifest", type=Path, required=True)
    parser.add_argument("--runtime-signature", type=Path, required=True)
    parser.add_argument("--trust", type=Path, default=ROOT / "packaging/update-trust.json")
    args = parser.parse_args()
    runtime = verify_manifest(
        args.runtime_manifest.read_bytes(),
        args.runtime_signature.read_bytes(),
        load_trust(args.trust),
        installed=True,
    )
    descriptor = build(args.output, args.version, runtime)
    print(json.dumps(descriptor, indent=2))


if __name__ == "__main__":
    main()
