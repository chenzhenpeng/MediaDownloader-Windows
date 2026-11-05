import hashlib

import pytest

from media_downloader.official_environments import OfficialEnvironments

HASH = hashlib.sha256(b"authenticated-wheel-fixture").hexdigest()


def prepare(store, identifier):
    directory = store.directory(identifier)
    (directory / "Scripts").mkdir(parents=True)
    (directory / "Scripts/python.exe").write_bytes(b"test-interpreter-not-executed")
    (directory / "package.py").write_text("fixture")

    def probe(path):
        return {
            "version": "2.4.0",
            "wheel_sha256": HASH,
            "package_origin": str(path / "Lib/site-packages/parsehub"),
            "client_preview_conversion": True,
            "local_transfer_bytes_verified": True,
            "progress_callback_received": True,
        }

    return probe


def test_validate_switch_restart_and_rollback(tmp_path):
    store = OfficialEnvironments(tmp_path)
    assert store.resolve() is None
    for identifier in ("first", "second"):
        probe = prepare(store, identifier)
        store.validate(identifier, version="2.4.0", wheel_hash=HASH, probe=probe)
    store.select("first", expected_generation=0)
    running_task = store.resolve()
    store.select("second", expected_generation=1)
    assert running_task == store.directory("first")
    restarted = OfficialEnvironments(tmp_path)
    assert restarted.resolve() == store.directory("second")
    restarted.rollback(expected_generation=2)
    assert restarted.resolve() == running_task


def test_unvalidated_changed_and_stale_selection_leave_current_untouched(tmp_path):
    store = OfficialEnvironments(tmp_path)
    probe = prepare(store, "good")
    store.validate("good", version="2.4.0", wheel_hash=HASH, probe=probe)
    store.select("good", expected_generation=0)
    prepare(store, "unvalidated")
    with pytest.raises(ValueError):
        store.select("unvalidated", expected_generation=1)
    with pytest.raises(ValueError):
        store.select("good", expected_generation=0)
    assert store.snapshot()["generation"] == 1
    (store.directory("good") / "package.py").write_text("tampered")
    with pytest.raises(ValueError):
        store.resolve()


@pytest.mark.parametrize("identifier", ["../escape", "a/b", "", "C:\\external"])
def test_reject_outside_directory(tmp_path, identifier):
    with pytest.raises(ValueError):
        OfficialEnvironments(tmp_path).directory(identifier)


def test_failed_or_mutating_probe_cannot_be_selected(tmp_path):
    store = OfficialEnvironments(tmp_path)
    original = prepare(store, "bad")

    def probe(directory):
        report = original(directory)
        (directory / "extra.py").write_text("changed")
        return report

    with pytest.raises(ValueError, match="changed"):
        store.validate("bad", version="2.4.0", wheel_hash=HASH, probe=probe)
    with pytest.raises(ValueError):
        store.select("bad", expected_generation=0)
    assert store.snapshot()["active"] is None


def two_environments(tmp_path):
    store = OfficialEnvironments(tmp_path)
    for identifier in ("stable", "candidate"):
        probe = prepare(store, identifier)
        store.validate(identifier, version="2.4.0", wheel_hash=HASH, probe=probe)
    store.select("stable", expected_generation=0)
    return store


def test_startup_failure_restores_previous_and_quarantines_candidate(tmp_path):
    store = two_environments(tmp_path)
    old_task = store.reserve_launch()
    store.launch_ready(old_task["token"])
    store.select("candidate", expected_generation=1)
    launch = store.reserve_launch()
    restarted = OfficialEnvironments(tmp_path)
    assert restarted.finish_launch(launch["token"], startup_failed=True)
    assert restarted.resolve() == store.directory("stable")
    assert old_task["directory"] == store.directory("stable")
    with pytest.raises(ValueError, match="quarantined"):
        store.select("candidate", expected_generation=3)
    assert not store.finish_launch(old_task["token"], startup_failed=True)
    with pytest.raises(ValueError):
        store.finish_launch(launch["token"], startup_failed=True)


def test_platform_failure_after_handshake_does_not_rollback(tmp_path):
    store = two_environments(tmp_path)
    store.select("candidate", expected_generation=1)
    launch = store.reserve_launch()
    store.launch_ready(launch["token"])
    assert not store.finish_launch(launch["token"], startup_failed=True)
    assert store.resolve() == store.directory("candidate")


def test_delayed_failure_cannot_replace_new_selection(tmp_path):
    store = two_environments(tmp_path)
    store.select("candidate", expected_generation=1)
    launch = store.reserve_launch()
    store.rollback(expected_generation=2)
    assert not store.finish_launch(launch["token"], startup_failed=True)
    assert store.resolve() == store.directory("stable")


def test_failure_without_healthy_previous_disables_candidate(tmp_path):
    store = two_environments(tmp_path)
    launch = store.reserve_launch()
    assert not store.finish_launch(launch["token"], startup_failed=True)
    assert store.resolve() is None
