import hashlib
import json
import shutil
import time
from dataclasses import asdict

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.release_engine import package_release
from test_official_install import wheel_file

from media_downloader import PROTOCOL
from media_downloader.component_store import ComponentStore
from media_downloader.component_updates import ProfileUpdateManager
from media_downloader.execution_profile import KINDS, compose, load_bundle
from media_downloader.official_packages import extract_wheel
from media_downloader.update_contracts import Trust, UpdateError


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def split_bundle(tmp_path):
    root = tmp_path / "bundle"
    roots = {kind: root / kind for kind in KINDS}
    for directory in roots.values():
        directory.mkdir(parents=True)
    contract = {
        "python": "3.13.17",
        "marker_environment": {"sys_platform": "win32"},
        "dependencies": {},
        "extras": {},
    }
    descriptors = {
        "python-runtime": {
            "version": "1.0.0",
            "abi": 1,
            "identity": "rt1-" + "1" * 24,
            "python": "3.13.17",
            "contract": contract,
        },
        "worker": {
            "version": "0.3.0",
            "protocol": PROTOCOL,
            "requires": {
                "environment_abi": 1,
                "python": ">=3.13,<3.14",
                "parsehub": ">=2.4,<3",
                "media_tools": ">=1,<2",
            },
        },
        "media-tools": {"version": "1.0.0", "files": {}},
    }
    (roots["python-runtime"] / "python.exe").write_bytes(b"test interpreter, never executed")
    (roots["worker"] / "worker_entry.py").write_text("# test entry")
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        (roots["media-tools"] / name).write_bytes(name.encode())
        descriptors["media-tools"]["files"][name] = hashlib.sha256(name.encode()).hexdigest()
    archive, wheel = wheel_file(tmp_path, "2.4.0")
    extract_wheel(archive, wheel, contract, roots["parsehub"] / "python")
    (roots["parsehub"] / wheel.filename).write_bytes(archive.read_bytes())
    descriptors["parsehub"] = {"version": wheel.version, "wheel": asdict(wheel)}
    for kind, data in descriptors.items():
        write(roots[kind] / "component.json", {"schema": 1, "kind": kind, "target": "windows-x86_64", **data})
    write(root / "profile.json", {"schema": 1, "components": {kind: kind for kind in KINDS}})
    return root, roots


@pytest.fixture
def store_and_release(tmp_path, split_bundle):
    root, roots = split_bundle
    key = Ed25519PrivateKey.generate()
    source = tmp_path / "worker-update"
    source.mkdir()
    data = json.loads((roots["worker"] / "component.json").read_bytes())
    data["version"] = "0.3.1"
    write(source / "component.json", data)
    (source / "worker_entry.py").write_text("# worker repair")
    feed = tmp_path / "feed"
    package_release(source, feed, key, sequence=1, channel="stable", key_id="test")
    trust = Trust("stable", {"test": key.public_key().public_bytes_raw()}, local_feed=feed)
    probes = []
    store = ComponentStore(
        tmp_path / "data",
        trust,
        load_bundle(root),
        probe=lambda engine, **_: probes.append(engine.component_versions),
    )
    return store, feed, probes


def install(store, feed, **kwargs):
    return store.install(
        feed / "engine.zip",
        (feed / "release.json").read_bytes(),
        (feed / "release.sig").read_bytes(),
        **kwargs,
    )


def test_worker_only_update_reuses_all_other_directories_and_survives_restart(store_and_release):
    store, feed, probes = store_and_release
    identity, engine = install(store, feed)
    assert store.state()["current"] == "bundled"
    assert engine.component_versions["worker"] == "0.3.1"
    for kind in ("python-runtime", "parsehub", "media-tools"):
        assert engine.components[kind] == store.bundled.components[kind]
    assert engine.program == store.bundled.program
    assert len(list((store.root / "components").iterdir())) == 1
    store.begin(identity)
    store.confirm(identity)
    restarted = ComponentStore(store.root, store.trust, store.bundled, probe=store.probe)
    assert restarted.recover() == engine
    assert probes == [engine.component_versions]


def test_interrupted_switch_rolls_back_whole_profile(store_and_release):
    store, feed, _ = store_and_release
    identity, _ = install(store, feed)
    store.begin(identity)
    assert store.recover() == store.bundled
    assert store.state()["pending"] is None


def test_failed_health_check_never_changes_active_profile(store_and_release):
    store, feed, _ = store_and_release

    def fail(*_, **__):
        raise RuntimeError("simulated handshake failure")

    store.probe = fail
    with pytest.raises(RuntimeError):
        install(store, feed)
    assert store.state()["current"] == "bundled"
    assert not list((store.root / "profiles").rglob("healthy.json"))


def test_signed_worker_tampering_cannot_be_recovered(store_and_release):
    store, feed, _ = store_and_release
    identity, engine = install(store, feed)
    store.begin(identity)
    store.confirm(identity)
    (type(store.root)(engine.components["worker"]) / "worker_entry.py").write_text("# modified")
    assert store.recover() == store.bundled


def test_bad_signature_does_not_execute_candidate(store_and_release):
    store, feed, probes = store_and_release
    with pytest.raises(UpdateError):
        store.install(feed / "engine.zip", (feed / "release.json").read_bytes(), b"0" * 64)
    assert not probes
    assert store.state()["current"] == "bundled"


def test_prune_preserves_previous_combination_and_referenced_components(store_and_release):
    store, feed, _ = store_and_release
    identity, engine = install(store, feed)
    store.begin(identity)
    store.confirm(identity)
    store.begin("bundled")
    store.confirm("bundled")
    store.prune()
    assert store.installed(identity) == engine


def test_incompatible_worker_environment_is_rejected_before_probe(split_bundle):
    _, roots = split_bundle
    path = roots["worker"] / "component.json"
    data = json.loads(path.read_bytes())
    data["requires"]["environment_abi"] = 2
    write(path, data)
    with pytest.raises(ValueError, match="Incompatible"):
        compose(roots)


def test_bundle_paths_cannot_escape_root(split_bundle):
    root, _ = split_bundle
    data = json.loads((root / "profile.json").read_bytes())
    data["components"]["worker"] = "../other"
    write(root / "profile.json", data)
    with pytest.raises(UpdateError):
        load_bundle(root)


def test_update_manager_downloads_only_worker_and_atomically_activates(store_and_release, tmp_path):
    from PySide6.QtCore import QCoreApplication, QObject, Signal

    from media_downloader.repository import Store
    from media_downloader.update_contracts import verify_manifest

    app = QCoreApplication.instance() or QCoreApplication([])
    engines, feed, _ = store_and_release
    raw, signature = (feed / "release.json").read_bytes(), (feed / "release.sig").read_bytes()
    manifest = verify_manifest(raw, signature, engines.trust)
    engines.accept_catalog = lambda *_: [(manifest, raw, signature)]
    downloaded = []

    class Feed:
        def check(self, **_):
            return b"catalog boundary", b"signature boundary"

        def download(self, item, directory, **_):
            downloaded.append(item["component"])
            target = directory / "candidate.zip"
            shutil.copy2(feed / "engine.zip", target)
            return target

    class Service(QObject):
        engine_activated = Signal(object)
        engine_switch_failed = Signal(str)
        engine_unhealthy = Signal()
        changed = Signal()

        def __init__(self):
            super().__init__()
            self.engine = engines.bundled
            self.store = Store(tmp_path / "task-data.sqlite3")
            self.running, self.verifications = {}, {}

        def switch_engine(self, engine):
            self.engine = engine
            self.engine_activated.emit(engine)

        def resume_dispatch(self):
            self.dispatch_paused = False

    service = Service()
    updates = ProfileUpdateManager(service, engines, feed=Feed())
    updates.timer.stop()

    def wait_for(status):
        deadline = time.monotonic() + 10
        while updates.status != status and time.monotonic() < deadline:
            app.processEvents()
            updates._tick()
            time.sleep(0.01)
        assert updates.status == status, updates.message

    try:
        updates.check("engine")
        wait_for("available")
        assert [item["component"] for item in updates.manifest["components"]] == ["worker"]
        updates.install()
        wait_for("updated")
        assert downloaded == ["worker"]
        assert service.engine.component_versions["worker"] == "0.3.1"
        assert engines.recover() == service.engine
    finally:
        updates.shutdown()
        service.store.close()


def test_local_tools_modified_after_selection_are_rejected(store_and_release, monkeypatch, tmp_path):
    from media_downloader import local_media_tools

    store, _, _ = store_and_release
    original = type(store.root)(store.bundled.components["media-tools"])
    local = tmp_path / "local-tools"
    shutil.copytree(original, local)
    data = json.loads((local / "component.json").read_bytes())
    data["external_directory"] = str(local.resolve())
    identity = (
        "media-tools-local-" + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]
    )
    monkeypatch.setattr(local_media_tools, "inspect_local_tools", lambda _: (identity, data))
    profile, engine = store.configure_tools(local)
    store.begin(profile)
    store.confirm(profile)
    assert store.recover() == engine
    (local / "ffmpeg.exe").write_bytes(b"changed external executable")
    assert store.recover() == store.bundled
    assert local.exists()  # Recovery never deletes a user-owned tool directory.
