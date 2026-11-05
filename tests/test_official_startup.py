import pytest
from test_official_environments import two_environments

from media_downloader.official_startup import prepare_launch


def test_preflight_failure_rolls_back_and_does_not_retry_task(tmp_path):
    store = two_environments(tmp_path)
    store.select("candidate", expected_generation=1)
    calls = []

    def fail(directory):
        calls.append(directory)
        raise TimeoutError("fixture timeout")

    with pytest.raises(TimeoutError):
        prepare_launch(store, check=fail)
    assert calls == [store.directory("candidate")]
    assert store.resolve() == store.directory("stable")


def test_preflight_version_mismatch_is_rejected(tmp_path):
    store = two_environments(tmp_path)
    store.select("candidate", expected_generation=1)
    with pytest.raises(ValueError, match="version"):
        prepare_launch(store, check=lambda _: {"version": "9.9.9"})
    assert store.resolve() == store.directory("stable")


def test_cancelled_preflight_does_not_quarantine(tmp_path):
    store = two_environments(tmp_path)

    def cancel(_):
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        prepare_launch(store, check=cancel)
    assert store.resolve() == store.directory("stable")


def test_ready_launch_stays_pinned_after_selection_changes(tmp_path):
    store = two_environments(tmp_path)
    lease = prepare_launch(store, check=lambda _: {"version": "2.4.0"})
    store.select("candidate", expected_generation=1)
    assert lease["directory"] == store.directory("stable")
    store.finish_launch(lease["token"])
    assert store.resolve() == store.directory("candidate")
