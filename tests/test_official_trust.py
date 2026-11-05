import hashlib
import json
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from media_downloader.official_trust import VerifiedOfficialEnvironments
from media_downloader.update_contracts import Trust


def candidate(tmp_path, *, identifier="candidate", key=None, store=None):
    key = key or Ed25519PrivateKey.generate()
    trust = Trust("beta", {"test": key.public_key().public_bytes_raw()})
    store = store or VerifiedOfficialEnvironments(tmp_path / "store", trust)
    directory = store.directory(identifier)
    (directory / "Scripts").mkdir(parents=True)
    (directory / "Scripts/python.exe").write_bytes(b"not-executed-fixture")
    entries = {
        "parsehub/__init__.py": b"# official fixture",
        "parsehub-2.4.0.dist-info/METADATA": b"Name: parsehub\nVersion: 2.4.0\n",
    }
    wheel = tmp_path / f"{identifier}.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
            path = directory / "Lib/site-packages" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    manifest = {
        "schema": 1,
        "kind": "official-environment",
        "target": "windows-x86_64",
        "channel": "beta",
        "key_id": "test",
        "sequence": 1,
        "version": "2.4.0",
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "files": json.loads(store._inventory(identifier)),
    }
    calls = []

    def probe(path):
        calls.append(path)
        return {
            "version": "2.4.0",
            "wheel_sha256": manifest["wheel_sha256"],
            "package_origin": str(path / "Lib/site-packages/parsehub"),
            "client_preview_conversion": True,
            "local_transfer_bytes_verified": True,
            "progress_callback_received": True,
        }

    return store, key, manifest, wheel, probe, calls


def admit(store, key, manifest, wheel, probe, identifier="candidate"):
    raw = json.dumps(manifest).encode()
    store.admit(identifier, raw, key.sign(raw), wheel, probe=probe)


def test_signed_candidate_reopens_and_requires_same_trust(tmp_path):
    store, key, manifest, wheel, probe, calls = candidate(tmp_path)
    admit(store, key, manifest, wheel, probe)
    assert len(calls) == 1
    store.select("candidate", expected_generation=0)
    assert VerifiedOfficialEnvironments(store.root, store.trust).resolve() == store.directory("candidate")
    other = Ed25519PrivateKey.generate()
    wrong_trust = Trust("beta", {"test": other.public_key().public_bytes_raw()})
    with pytest.raises(ValueError, match="signature"):
        VerifiedOfficialEnvironments(store.root, wrong_trust).resolve()


@pytest.mark.parametrize("failure", ["signature", "expiry", "inventory", "wheel", "channel"])
def test_reject_before_candidate_execution(tmp_path, failure):
    store, key, manifest, wheel, probe, calls = candidate(tmp_path)
    if failure == "signature":
        key = Ed25519PrivateKey.generate()
    elif failure == "expiry":
        manifest["expires_at"] = "2020-01-01T00:00:00+00:00"
    elif failure == "inventory":
        (store.directory("candidate") / "extra.py").write_text("unexpected")
    elif failure == "wheel":
        wheel.write_bytes(b"substituted-wheel")
    else:
        manifest["channel"] = "stable"
    with pytest.raises(ValueError):
        admit(store, key, manifest, wheel, probe)
    assert calls == [] and store.snapshot()["active"] is None


def test_signed_inventory_cannot_hide_modified_official_code(tmp_path):
    store, key, manifest, wheel, probe, calls = candidate(tmp_path)
    (store.directory("candidate") / "Lib/site-packages/parsehub/__init__.py").write_text("# fork")
    manifest["files"] = json.loads(store._inventory("candidate"))
    with pytest.raises(ValueError, match="original wheel"):
        admit(store, key, manifest, wheel, probe)
    assert calls == []


def test_local_inventory_rewrite_cannot_bypass_signed_inventory(tmp_path):
    store, key, manifest, wheel, probe, _ = candidate(tmp_path)
    admit(store, key, manifest, wheel, probe)
    store.select("candidate", expected_generation=0)
    (store.directory("candidate") / "extra.py").write_text("changed")
    with store._connect() as db:
        db.execute("UPDATE environments SET inventory=?", (store._inventory("candidate"),))
    with pytest.raises(ValueError, match="authenticated manifest"):
        store.resolve()


def test_replayed_manifest_cannot_execute_another_candidate(tmp_path):
    store, key, manifest, wheel, probe, _ = candidate(tmp_path)
    admit(store, key, manifest, wheel, probe)
    store, key, manifest, wheel, probe, calls = candidate(tmp_path, identifier="second", key=key, store=store)
    with pytest.raises(ValueError, match="replay"):
        admit(store, key, manifest, wheel, probe, "second")
    assert calls == []


def test_higher_sequence_does_not_hide_upstream_downgrade(tmp_path):
    store, key, manifest, wheel, probe, _ = candidate(tmp_path)
    admit(store, key, manifest, wheel, probe)
    store, key, manifest, wheel, probe, calls = candidate(tmp_path, identifier="older", key=key, store=store)
    manifest.update(sequence=2, version="2.3.0")
    with pytest.raises(ValueError, match="upstream downgrade"):
        admit(store, key, manifest, wheel, probe, "older")
    assert calls == []


def test_change_between_authentication_and_probe_is_rejected(tmp_path, monkeypatch):
    store, key, manifest, wheel, probe, calls = candidate(tmp_path)
    original = store._inventory
    changed = False

    def inventory(identifier):
        nonlocal changed
        result = original(identifier)
        if not changed:
            changed = True
            (store.directory(identifier) / "Scripts/python.exe").write_bytes(b"substituted")
        return result

    monkeypatch.setattr(store, "_inventory", inventory)
    with pytest.raises(ValueError, match="before probe"):
        admit(store, key, manifest, wheel, probe)
    assert calls == []


def test_superseded_admission_cannot_leave_selectable_unsigned_record(tmp_path):
    store, key, manifest, wheel, original, _ = candidate(tmp_path)

    def probe(path):
        with store._connect() as db:
            db.execute("UPDATE official_trust_state SET sequence=2")
        return original(path)

    with pytest.raises(ValueError, match="replay"):
        admit(store, key, manifest, wheel, probe)
    with pytest.raises(ValueError, match="authenticated provenance"):
        store.select("candidate", expected_generation=0)
    assert store.snapshot()["active"] is None
