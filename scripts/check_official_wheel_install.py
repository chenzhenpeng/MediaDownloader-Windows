"""Exercise a real, unchanged wheel installation with a controlled version baseline."""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from media_downloader.engine import resolve_engine  # noqa: E402
from media_downloader.official_install import install  # noqa: E402
from media_downloader.official_packages import OfficialWheel  # noqa: E402
from media_downloader.update_contracts import Trust  # noqa: E402
from media_downloader.update_store import EngineStore  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.root.exists():
        raise ValueError("Acceptance needs a fresh isolated directory")
    runtime = resolve_engine(args.runtime.resolve())
    metadata = json.loads((args.runtime / "engine.json").read_bytes())
    wheel = OfficialWheel(**metadata["official_wheel"])
    # PyPI currently has one stable version. Change only the parent service's
    # comparison baseline, never the upstream archive or runtime package bytes.
    controlled = replace(runtime, parser_version="0")
    store = EngineStore(args.root.resolve(), Trust("stable", {}), controlled)
    original = args.runtime / "upstream" / wheel.filename
    name, selected = install(store, wheel, original)
    assert store.recover() == controlled
    store.begin(name)
    store.confirm(name)
    assert store.recover() == selected
    assert selected.program == runtime.program
    store.begin("bundled")
    store.confirm("bundled")
    assert store.recover() == controlled
    report = {
        "passed": True,
        "version": wheel.version,
        "sha256": wheel.sha256,
        "original_wheel_bytes": wheel.size,
        "runtime_reused": True,
        "install_probe_restart_rollback": True,
        "controlled_comparison_baseline": True,
    }
    (args.root / "acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
