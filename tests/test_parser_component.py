import json
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.build_parser_bundle import build
from scripts.release_engine import package_release

from media_downloader import PROTOCOL, UPSTREAM_SHA
from media_downloader.engine import resolve_engine
from media_downloader.parser_runtime import runtime_id
from media_downloader.update_contracts import Trust, UpdateError
from media_downloader.update_store import EngineStore

ROOT = Path(__file__).resolve().parents[1]


def make_runtime(path, identifier):
    path.mkdir()
    (path / "media-engine.exe").write_bytes(b"not-executed-unit-fixture")
    (path / "engine.json").write_text(
        json.dumps(
            {
                "engine_version": "runtime-test",
                "upstream_sha": UPSTREAM_SHA,
                "protocol": PROTOCOL,
                "target": "windows-x86_64",
                "runtime_id": identifier,
            }
        ),
        encoding="utf-8",
    )
    return resolve_engine(path)


def test_parser_update_reuses_runtime_and_rejects_dependency_mismatch(tmp_path):
    identifier = runtime_id(ROOT / "uv.lock")
    runtime = make_runtime(tmp_path / "runtime", identifier)
    source = tmp_path / "source"
    build(source, "parser-test", {"runtime_id": identifier})
    assert not list(source.rglob("*.exe")) and not list(source.rglob("*.dll"))
    key = Ed25519PrivateKey.generate()
    output = tmp_path / "signed"
    manifest = package_release(source, output, key, sequence=1)
    assert manifest["component"] == "parsehub"
    assert manifest["app_min_version"] == "0.2.0.dev11"
    assert manifest["size_bytes"] < 1024**2
    trust = Trust("beta", {"local-test": key.public_key().public_bytes_raw()}, local_feed=output)
    raw, signature = (output / "release.json").read_bytes(), (output / "release.sig").read_bytes()
    store = EngineStore(tmp_path / "state", trust, runtime, probe=lambda engine, **kwargs: None)
    identity, selected = store.install(output / "engine.zip", raw, signature)
    assert selected.program == runtime.program
    assert selected.runtime_version == runtime.version
    assert selected.arguments[0] == "--component-dir"
    store.begin(identity)
    store.confirm(identity)
    assert store.recover().version == "parser-test"
    store.begin("bundled")
    store.confirm("bundled")
    assert store.recover() == runtime
    wrong = make_runtime(tmp_path / "wrong-runtime", "rt1-" + "0" * 24)
    rejected = EngineStore(tmp_path / "incompatible", trust, wrong)
    with pytest.raises(UpdateError) as error:
        rejected.accept(raw, signature)
    assert error.value.code == "UPDATE_RUNTIME"
    assert not (rejected.root / "update-policy.json").exists()


def test_runtime_contract_ignores_parser_version_but_tracks_dependencies(tmp_path):
    lock = tmp_path / "lock.toml"
    content = """[[package]]
name = "parsehub"
version = "2.4.0"
source = {editable = "upstream"}
[[package]]
name = "dependency"
version = "1.0"
source = {registry = "https://pypi.org/simple"}
"""
    lock.write_text(content, encoding="utf-8")
    original = runtime_id(lock)
    lock.write_text(content.replace('"2.4.0"', '"2.5.0"'), encoding="utf-8")
    assert runtime_id(lock) == original
    lock.write_text(content.replace('"1.0"', '"2.0"'), encoding="utf-8")
    assert runtime_id(lock) != original


def test_selected_parser_is_external_and_does_not_write_bytecode(tmp_path):
    identifier = "rt1-" + "1" * 24
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({"runtime_id": identifier}), encoding="utf-8")
    component = tmp_path / "component"
    code = component / "python/parsehub"
    code.mkdir(parents=True)
    (code / "__init__.py").write_text("MARKER = 'selected-component'\n", encoding="utf-8")
    (component / "engine.json").write_text(
        json.dumps(
            {
                "component": "parsehub",
                "requires_runtime_id": identifier,
                "protocol": PROTOCOL,
                "target": "windows-x86_64",
                "upstream_sha": UPSTREAM_SHA,
                "engine_version": "test-parser",
            }
        ),
        encoding="utf-8",
    )
    script = (
        "from pathlib import Path; import sys; from media_downloader.parser_runtime import activate; "
        "activate(Path(sys.argv[1]),Path(sys.argv[2])); import parsehub; "
        "assert parsehub.MARKER=='selected-component'; assert sys.dont_write_bytecode"
    )
    subprocess.run([sys.executable, "-c", script, str(component), str(runtime)], check=True)
    assert not list(code.rglob("*.pyc"))
