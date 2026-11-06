"""Real isolated acceptance: a signed worker-only update reuses all large components."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from release_engine import package_release  # noqa: E402

from media_downloader.component_store import ComponentStore  # noqa: E402
from media_downloader.engine import resolve_engine  # noqa: E402
from media_downloader.update_contracts import Trust  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.root.exists():
        raise ValueError("Acceptance requires a new isolated directory")
    args.root.mkdir(parents=True)
    bundled = resolve_engine(args.bundle.resolve())
    source = args.root / "worker"
    shutil.copytree(bundled.components["worker"], source)
    metadata = json.loads((source / "component.json").read_bytes())
    # A controlled higher worker version exercises update selection without inventing an upstream release.
    metadata["version"] = "0.3.1"
    (source / "component.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    key = Ed25519PrivateKey.generate()
    feed = args.root / "feed"
    manifest = package_release(source, feed, key, sequence=1, channel="stable", key_id="acceptance")
    trust = Trust("stable", {"acceptance": key.public_key().public_bytes_raw()}, local_feed=feed)
    store = ComponentStore(args.root / "data", trust, bundled)
    identity, candidate = store.install(
        feed / "engine.zip", (feed / "release.json").read_bytes(), (feed / "release.sig").read_bytes()
    )
    for kind in ("python-runtime", "parsehub", "media-tools"):
        assert candidate.components[kind] == bundled.components[kind]
    store.begin(identity)
    store.confirm(identity)
    restarted = ComponentStore(store.root, trust, bundled)
    assert restarted.recover() == candidate
    # The same media binaries can be selected as an explicit local directory without copying them.
    local_id, local = store.configure_tools(bundled.components["media-tools"])
    store.begin(local_id)
    store.confirm(local_id)
    assert ComponentStore(store.root, trust, bundled).recover() == local
    restored_id, _ = store.configure_tools()
    store.begin(restored_id)
    assert store.recover() == local  # Interrupted selection rolls back the whole combination.
    report = {
        "passed": True,
        "worker_archive_bytes": manifest["size_bytes"],
        "large_component_directories_reused": True,
        "signed_install_and_recovery": True,
        "local_tools_verified": True,
        "interrupted_switch_rolled_back": True,
        "components": candidate.component_versions,
    }
    (args.root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
