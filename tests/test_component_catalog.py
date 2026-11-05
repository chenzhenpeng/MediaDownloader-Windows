import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.build_component_catalog import build as catalog
from scripts.build_parser_bundle import build as parser_bundle
from scripts.release_engine import package_release

from media_downloader import PROTOCOL, UPSTREAM_SHA
from media_downloader.component_catalog import choose, newer, verify_catalog
from media_downloader.engine import Engine, resolve_engine
from media_downloader.parser_runtime import runtime_id
from media_downloader.update_contracts import Trust, UpdateError
from media_downloader.update_store import EngineStore


def release(tmp_path, key, version, *, identifier="", component="engine"):
    source = tmp_path / f"source-{version}-{component}"
    source.mkdir()
    (source / "media-engine.exe").write_bytes(b"unit-fixture-not-executed")
    descriptor = {
        "protocol": PROTOCOL,
        "target": "windows-x86_64",
        "engine_version": version,
        "upstream_sha": UPSTREAM_SHA,
        "patchset": "unit",
        "runtime_id": identifier,
    }
    (source / "engine.json").write_text(json.dumps(descriptor), encoding="utf-8")
    output = tmp_path / f"feed-{version}-{component}"
    manifest = package_release(source, output, key, sequence=1)
    return output, manifest, (output / "release.json").read_bytes(), (output / "release.sig").read_bytes()


def test_normal_updates_reject_downgrades_and_compare_components_separately():
    engine = Engine(
        "2.0.0", UPSTREAM_SHA, "unused", runtime_version="1.4.0", parser_component_version="2.0.0"
    )
    assert not newer({"engine_version": "1.2.0"}, engine)
    assert newer({"engine_version": "1.5.0"}, engine)
    assert not newer({"engine_version": "1.9.0", "component": "parsehub"}, engine)
    assert newer({"engine_version": "2.1.0", "component": "parsehub"}, engine)
    assert not newer({"engine_version": "unknown-legacy"}, engine)
    parser = replace(engine, component="parsehub")
    assert not newer({"engine_version": "1.6.0", "parser_component_version": "1.9.0"}, parser)
    assert newer({"engine_version": "1.6.0", "parser_component_version": "2.0.0"}, parser)


def test_separate_settings_checks_cannot_select_the_other_component():
    engine = Engine("1.4.0", UPSTREAM_SHA, "unused", runtime_id="runtime")
    runtime = ({"engine_version": "1.5.0"}, b"runtime", b"signature")
    parser = (
        {"component": "parsehub", "engine_version": "1.6.0", "requires_runtime_id": "runtime"},
        b"parser",
        b"signature",
    )
    assert choose([runtime, parser], engine, "runtime", component="parsehub") == parser
    assert choose([runtime, parser], engine, "runtime", component="engine") == runtime
    assert choose([runtime], engine, "runtime", component="parsehub") is None


def test_catalog_is_signed_bounded_and_replay_protected(tmp_path):
    key = Ed25519PrivateKey.generate()
    trust = Trust("beta", {"local-test": key.public_key().public_bytes_raw()}, local_feed=tmp_path)
    _, _, raw, signature = release(tmp_path, key, "1.5.0")
    body, signed = catalog([(raw, signature)], key, trust, 3)
    _, candidates = verify_catalog(body, signed, trust)
    assert choose(candidates, Engine("1.4.0", UPSTREAM_SHA, "unused"), "")[0]["engine_version"] == "1.5.0"
    store = EngineStore(tmp_path / "state", trust, Engine("1.4.0", UPSTREAM_SHA, "unused"))
    assert len(store.accept_catalog(body, signed)) == 1
    for altered, sig in ((body + b" ", signed), (body, b"0" * 64)):
        with pytest.raises(UpdateError):
            store.accept_catalog(altered, sig)
    older, older_sig = catalog([(raw, signature)], key, trust, 2)
    with pytest.raises(UpdateError, match="过旧"):
        store.accept_catalog(older, older_sig)
    with pytest.raises(UpdateError):
        verify_catalog(body, signed, trust, now=datetime.now(UTC) + timedelta(days=31))
    wrong_target = json.loads(raw)
    wrong_target["target"] = "linux-x86_64"
    changed = json.dumps(wrong_target).encode()
    data = json.loads(body)
    import base64

    data["releases"][0] = {
        "manifest": base64.b64encode(changed).decode(),
        "signature": base64.b64encode(key.sign(changed)).decode(),
    }
    body = json.dumps(data).encode()
    assert verify_catalog(body, key.sign(body), trust)[1] == []


def test_parser_binds_updated_runtime_and_pruning_keeps_composition(tmp_path):
    from pathlib import Path

    identifier = runtime_id(Path(__file__).resolve().parents[1] / "uv.lock")
    key = Ed25519PrivateKey.generate()
    output, _, raw, signature = release(tmp_path, key, "1.5.0", identifier=identifier)
    trust = Trust("beta", {"local-test": key.public_key().public_bytes_raw()}, local_feed=output)
    bundled = replace(resolve_engine(output.parent / "source-1.5.0-engine"), runtime_id="rt1-" + "0" * 24)
    store = EngineStore(tmp_path / "state", trust, bundled, probe=lambda *a, **kw: None)
    runtime_identity, runtime = store.install(output / "engine.zip", raw, signature)
    store.begin(runtime_identity)
    store.confirm(runtime_identity)
    parser = tmp_path / "parser"
    parser_bundle(parser, "2.1.0", {"runtime_id": identifier})
    parser_feed = tmp_path / "parser-feed"
    manifest = package_release(parser, parser_feed, key, sequence=1)
    raw, signature = (parser_feed / "release.json").read_bytes(), (parser_feed / "release.sig").read_bytes()
    identity, selected = store.install(parser_feed / "engine.zip", raw, signature)
    assert selected.program == runtime.program
    assert selected.component == "parsehub" and selected.runtime_version == "1.5.0"
    store.begin(identity)
    store.confirm(identity)
    assert store.recover() == selected
    # A second parser can make both current/last_good parser packages.
    parser2 = tmp_path / "parser2"
    parser_bundle(parser2, "2.2.0", {"runtime_id": identifier})
    feed2 = tmp_path / "parser-feed2"
    package_release(parser2, feed2, key, sequence=2)
    identity2, _ = store.install(
        feed2 / "engine.zip", (feed2 / "release.json").read_bytes(), (feed2 / "release.sig").read_bytes()
    )
    store.begin(identity2)
    store.confirm(identity2)
    store.prune()
    assert store.installed(runtime_identity).runtime_id == identifier
    store.begin(identity)
    store.confirm(identity)
    assert store.recover() == selected
    compatible = (manifest, raw, signature)
    incompatible = ({**manifest, "requires_runtime_id": "rt1-" + "f" * 24}, raw, signature)
    assert choose([incompatible], bundled, bundled.runtime_id) is None
    assert choose([compatible], runtime, identifier) == compatible
