import json
import stat
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PySide6.QtCore import QCoreApplication
from scripts.release_engine import package_release
from scripts.sync_upstream import apply_reviewed_patch
from test_worker_integration import wait_for

from media_downloader import PROTOCOL, UPSTREAM_SHA
from media_downloader.engine import Engine, resolve_engine
from media_downloader.service import TaskService
from media_downloader.storage import Store
from media_downloader.update_archive import extract_archive, safe_relative
from media_downloader.update_contracts import Trust, UpdateError, load_trust, release_id, verify_manifest
from media_downloader.update_feed import UpdateFeed
from media_downloader.update_manager import UpdateManager
from media_downloader.update_store import EngineStore, update_lock


@pytest.fixture
def signed_release(tmp_path):
    key = Ed25519PrivateKey.generate()
    source = tmp_path / "engine"
    source.mkdir()
    (source / "media-engine.exe").write_bytes(b"test-not-executable")
    (source / "engine.json").write_text(
        json.dumps(
            {
                "protocol": PROTOCOL,
                "target": "windows-x86_64",
                "engine_version": "test-e2",
                "upstream_sha": UPSTREAM_SHA,
                "patchset": "test",
                "yt-dlp": "test",
                "tools": {},
            }
        ),
        encoding="utf-8",
    )
    (source / "tools").mkdir()
    (source / "tools/test.dll").write_bytes(b"test-library")
    output = tmp_path / "feed"
    manifest = package_release(source, output, key, sequence=5)
    trust = Trust("beta", {"local-test": key.public_key().public_bytes_raw()}, local_feed=output)
    raw, signature = (output / "release.json").read_bytes(), (output / "release.sig").read_bytes()
    probes = []
    store = EngineStore(
        tmp_path / "app",
        trust,
        resolve_engine(),
        probe=lambda engine, **kwargs: probes.append(engine.version),
    )
    return key, output, manifest, trust, raw, signature, store, probes


def signed_change(key, raw, **fields):
    data = json.loads(raw)
    data.update(fields)
    changed = json.dumps(data).encode()
    return changed, key.sign(changed)


def test_signature_verified_before_json_and_unsigned_never_probed(signed_release):
    key, output, manifest, trust, raw, signature, store, probes = signed_release
    assert verify_manifest(raw, signature, trust)["engine_version"] == "test-e2"
    for bad_raw, bad_sig in ((raw + b" ", signature), (b"not json", signature), (raw, b"0" * 64)):
        with pytest.raises(UpdateError, match="验证|签名"):
            store.install(output / "engine.zip", bad_raw, bad_sig)
    assert probes == [] and store.state()["current"] == "bundled"


@pytest.mark.parametrize(
    "fields,code",
    [
        ({"protocol_version": 999}, "UPDATE_INCOMPATIBLE"),
        ({"target": "linux-x86_64"}, "UPDATE_INCOMPATIBLE"),
        ({"app_min_version": "99.0.0"}, "UPDATE_INCOMPATIBLE"),
        ({"channel": "stable"}, "UPDATE_MANIFEST"),
        ({"sequence": True}, "UPDATE_MANIFEST"),
        ({"expires_at": "2020-01-01T00:00:00Z", "published_at": "2019-01-01T00:00:00Z"}, "UPDATE_EXPIRED"),
        ({"engine_version": "../escaped"}, "UPDATE_MANIFEST"),
    ],
)
def test_signed_incompatible_and_expired_manifests_rejected(signed_release, fields, code):
    key, _, _, trust, raw, _, _, _ = signed_release
    changed, signature = signed_change(key, raw, **fields)
    with pytest.raises(UpdateError) as error:
        verify_manifest(changed, signature, trust)
    assert error.value.code == code


def test_replay_immutable_version_and_corrupt_policy(signed_release):
    key, _, _, _, raw, signature, store, _ = signed_release
    store.accept(raw, signature)
    assert store.accept(raw, signature)
    changed, signed = signed_change(key, raw, sequence=4)
    with pytest.raises(UpdateError) as error:
        store.accept(changed, signed)
    assert error.value.code == "UPDATE_REPLAY"
    changed, signed = signed_change(key, raw, sequence=6, sha256="f" * 64)
    with pytest.raises(UpdateError) as error:
        store.accept(changed, signed)
    assert error.value.code == "UPDATE_IMMUTABLE"
    (store.root / "update-policy.json").write_text("corrupt")
    with pytest.raises(UpdateError) as error:
        store.accept(raw, signature)
    assert error.value.code == "UPDATE_POLICY"


def test_install_switch_recovery_rollback_and_tampered_fallback(signed_release):
    _, output, manifest, trust, raw, signature, store, probes = signed_release
    identity, engine = store.install(output / "engine.zip", raw, signature)
    assert probes == ["test-e2"] and engine.version == "test-e2"
    assert store.state()["current"] == "bundled"
    store.begin(identity)
    assert store.recover() == store.bundled  # crash before handshake confirmation
    assert store.state()["pending"] is None
    store.begin(identity)
    store.confirm(identity)
    assert store.recover().version == "test-e2"
    assert verify_manifest(raw, signature, trust, installed=True, now=datetime.now(UTC) + timedelta(days=90))
    store.begin("bundled")
    store.confirm("bundled")
    assert store.state()["last_good"] == identity
    assert json.loads((store.root / "update-policy.json").read_bytes())["sequence"] == 5
    store.begin(identity)
    store.confirm(identity)
    installed = store.root / "engines" / identity / "payload/tools/test.dll"
    installed.write_bytes(b"tampered")
    assert store.recover() == store.bundled


def test_hash_and_health_failures_preserve_pointer(signed_release):
    _, output, _, _, raw, signature, store, probes = signed_release
    archive = output / "engine.zip"
    original = archive.read_bytes()
    archive.write_bytes(original[:-1])
    with pytest.raises(UpdateError) as error:
        store.install(archive, raw, signature)
    assert error.value.code == "UPDATE_HASH" and not probes
    archive.write_bytes(original)

    def unhealthy(*args, **kwargs):
        raise UpdateError("UPDATE_HEALTH", "bad health")

    store.probe = unhealthy
    with pytest.raises(UpdateError) as error:
        store.install(archive, raw, signature)
    assert error.value.code == "UPDATE_HEALTH"
    assert store.state()["current"] == "bundled" and store.recover() == store.bundled


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/escape",
        "C:/escape",
        "a\\b",
        "a/../b",
        "a/./b",
        "CON.txt",
        "file:stream",
        "a./b",
        "a /b",
        "x\x00y",
    ],
)
def test_unsafe_windows_archive_names_rejected(path):
    with pytest.raises(UpdateError):
        safe_relative(path)


def test_duplicate_and_symlink_archive_rejected_before_writing(tmp_path):
    for index, names in enumerate((("A", "a"), ("link",))):
        archive = tmp_path / f"bad{index}.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for name in names:
                info = zipfile.ZipInfo(name)
                if index:
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                bundle.writestr(info, b"x")
        with pytest.raises(UpdateError):
            extract_archive(
                archive,
                tmp_path / f"stage{index}",
                {"file_count": len(names), "unpacked_size_bytes": len(names)},
            )
        assert not list((tmp_path / f"stage{index}").iterdir())


def test_https_redirect_allowlist_and_interrupted_download(tmp_path):
    trust = Trust(
        "stable", {}, ("updates.example",), "https://updates.example/release", "https://updates.example/sig"
    )

    def redirect(request):
        return httpx.Response(302, headers={"location": "https://other.example/evil"})

    feed = UpdateFeed(trust, transport=httpx.MockTransport(redirect))
    with pytest.raises(UpdateError) as error:
        feed.bounded(trust.manifest_url, 100)
    assert error.value.code == "UPDATE_SOURCE"
    for url in (
        "http://updates.example/x",
        "https://updates.example:8443/x",
        "https://u:p@updates.example/x",
    ):
        with pytest.raises(UpdateError):
            trust.check_url(url)

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"short"

    feed = UpdateFeed(trust, transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=Stream())))
    with pytest.raises(UpdateError):
        feed.download({"artifact_url": "https://updates.example/zip", "size_bytes": 20}, tmp_path)
    assert not list(tmp_path.glob("*.part"))


def test_update_lock_is_exclusive(signed_release):
    store = signed_release[-2]
    with update_lock(store.root), pytest.raises(UpdateError):
        with update_lock(store.root):
            pass


def fixture_engine(version):
    return Engine(
        version, UPSTREAM_SHA, sys.executable, (str(Path(__file__).with_name("versioned_engine.py")), version)
    )


def test_pool_switch_waits_for_active_task_and_retains_attempt_versions(tmp_path, monkeypatch):
    app = QCoreApplication.instance()
    monkeypatch.setenv("TEST_DELAY", "1")
    monkeypatch.setenv("TEST_MEDIA_URL", "http://127.0.0.1:1/not-used")
    tasks = Store(tmp_path / "tasks.db")
    e1, e2 = fixture_engine("e1"), fixture_engine("e2")
    service = TaskService(tasks, engine=e1, max_workers=1)
    engines = EngineStore(tmp_path / "updates", Trust("beta", {}), e1)
    manager = UpdateManager(service, engines)
    try:
        ids = service.submit(
            ["https://www.douyin.com/video/81", "https://www.douyin.com/video/82"], str(tmp_path)
        )
        wait_for(app, lambda: bool(service.running))
        manager.prepared = ("test-e2-" + "a" * 12, e2)
        service.dispatch_paused = True
        manager.status, manager.job = "waiting", "install"
        assert tasks.get(ids[0])["state"] == "parsing"
        wait_for(app, lambda: manager.status == "updated")
        wait_for(app, lambda: tasks.get(ids[1])["state"] == "ready" and not service.running)
        assert tasks.attempts(ids[0])[0]["engine_version"] == "e1"
        assert tasks.attempts(ids[1])[0]["engine_version"] == "e2"
        assert engines.state()["current"].startswith("test-e2")
    finally:
        manager.shutdown()
        service.shutdown()
        tasks.close()


def test_bad_worker_handshake_recovers_without_restarting_ui(tmp_path):
    app = QCoreApplication.instance()
    tasks = Store(tmp_path / "tasks.db")
    e1 = fixture_engine("e1")
    service = TaskService(tasks, engine=e1, max_workers=1)
    engines = EngineStore(tmp_path / "updates", Trust("beta", {}), e1)
    manager = UpdateManager(service, engines)
    try:
        manager.prepared = ("bad-e2-" + "b" * 12, fixture_engine("broken"))
        manager.status, manager.job = "waiting", "install"
        wait_for(app, lambda: manager.status == "rolled_back")
        assert service.engine == e1 and engines.state()["current"] == "bundled"
        assert not service.dispatch_paused
    finally:
        manager.shutdown()
        service.shutdown()
        tasks.close()


def test_pinned_version_does_not_download_or_rollback(tmp_path):
    tasks = Store(tmp_path / "tasks.db")
    service = TaskService(tasks, engine=fixture_engine("e1"), max_workers=1)
    engines = EngineStore(tmp_path / "updates", Trust("beta", {}), service.engine)
    manager = UpdateManager(service, engines)
    try:
        tasks.set_setting("engine_update_locked", True)
        manager.manifest = {"size_bytes": 1}
        manager.status = "available"
        manager.install()
        manager.rollback()
        assert manager.future is None and service.engine.version == "e1"
        assert engines.state()["pending"] is None
    finally:
        manager.shutdown()
        service.shutdown()
        tasks.close()


def test_cancelled_install_and_disk_budget_never_probe(signed_release, monkeypatch):
    from types import SimpleNamespace

    import media_downloader.update_archive as archive_module

    _, output, _, _, raw, signature, store, probes = signed_release
    with pytest.raises(UpdateError) as error:
        store.install(output / "engine.zip", raw, signature, cancelled=lambda: True)
    assert error.value.code == "UPDATE_CANCELLED" and not probes
    monkeypatch.setattr(archive_module.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
    with pytest.raises(UpdateError) as error:
        store.install(output / "engine.zip", raw, signature)
    assert error.value.code == "UPDATE_DISK" and store.state()["current"] == "bundled"


def test_corrupt_pointer_recovers_without_resetting_replay_policy(signed_release):
    _, _, _, _, raw, signature, store, _ = signed_release
    store.accept(raw, signature)
    store.state_path.write_text("broken")
    assert store.recover() == store.bundled
    assert json.loads((store.root / "update-policy.json").read_bytes())["sequence"] == 5
    assert store.recovery_message


def test_prune_retains_current_and_last_good_and_unknown_directories(signed_release):
    store = signed_release[-2]
    names = ["e1-" + "a" * 12, "e2-" + "b" * 12, "e3-" + "c" * 12, "user-data"]
    for name in names:
        directory = store.root / "engines" / name
        directory.mkdir(parents=True)
        (directory / "keep.txt").write_text("owned fixture")
    state = store.state()
    store.write_state({**state, "current": names[2], "last_good": names[1]})
    store.prune()
    assert not (store.root / "engines" / names[0]).exists()
    assert all((store.root / "engines" / name / "keep.txt").exists() for name in names[1:])


def test_update_extraction_refuses_directory_junction(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("keep")
    link = tmp_path / "linked"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    try:
        with pytest.raises(UpdateError) as error:
            extract_archive(tmp_path / "not-opened.zip", link / "payload", {})
        assert error.value.code == "UPDATE_PATH" and sentinel.read_text() == "keep"
    finally:
        assert link.is_junction() and link.parent == tmp_path
        link.rmdir()


def test_candidate_is_placed_before_probe_but_unhealthy_pointer_cannot_boot(signed_release):
    _, output, manifest, _, raw, signature, store, _ = signed_release
    identity = release_id(manifest)

    def crash_probe(engine, **kwargs):
        assert "engines" in Path(engine.program).parts
        assert not (Path(engine.program).parents[1] / "healthy.json").exists()
        assert store.state()["current"] == "bundled"
        raise UpdateError("UPDATE_HEALTH", "simulated process crash")

    store.probe = crash_probe
    with pytest.raises(UpdateError):
        store.install(output / "engine.zip", raw, signature)
    state = store.state()
    store.write_state({**state, "current": identity})
    assert store.recover() == store.bundled


@pytest.mark.parametrize("contents", ["[]", "null", '{"keys":[]}'])
def test_malformed_trust_is_typed_configuration_error(tmp_path, contents):
    path = tmp_path / "trust.json"
    path.write_text(contents)
    with pytest.raises(UpdateError) as error:
        load_trust(path)
    assert error.value.code == "UPDATE_CONFIG"


def test_malformed_health_receipt_falls_back_to_bundled(signed_release):
    _, output, _, _, raw, signature, store, _ = signed_release
    identity, _ = store.install(output / "engine.zip", raw, signature)
    store.begin(identity)
    store.confirm(identity)
    (store.root / "engines" / identity / "healthy.json").write_text("[]")
    assert store.recover() == store.bundled


def test_patch_replay_isolated_from_outer_application_git_repository(tmp_path):
    subprocess.run(["git", "init", str(tmp_path / "repo")], check=True, capture_output=True)
    repository = tmp_path / "repo"
    (repository / "src").mkdir()
    outer = repository / "src/example.py"
    outer.write_text("old\n")
    candidate = repository / ".local/candidate"
    (candidate / "src").mkdir(parents=True)
    inner = candidate / "src/example.py"
    inner.write_text("old\n")
    patch = tmp_path / "test.patch"
    patch.write_text(
        "diff --git a/src/example.py b/src/example.py\n"
        "--- a/src/example.py\n+++ b/src/example.py\n@@ -1 +1 @@\n-old\n+new\n"
    )
    assert apply_reviewed_patch(candidate, patch)
    assert inner.read_text() == "new\n" and outer.read_text() == "old\n"
