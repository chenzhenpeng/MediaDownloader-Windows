import hashlib
import io
import json
import zipfile

import pytest

from media_downloader.engine import Engine
from media_downloader.official_install import install
from media_downloader.official_packages import OfficialWheel
from media_downloader.update_contracts import Trust, UpdateError
from media_downloader.update_store import EngineStore


def environment(tmp_path, *, probe=lambda *_, **__: None):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "engine.json").write_text(
        json.dumps(
            {
                "official_package_runtime": {
                    "adapter_abi": 1,
                    "python": "3.12.12",
                    "marker_environment": {"sys_platform": "win32"},
                    "dependencies": {},
                }
            }
        )
    )
    engine = Engine(
        "0.2.0",
        "runtime-sha",
        str(runtime / "python.exe"),
        runtime_id="rt1-" + "1" * 24,
        runtime_version="0.2.0",
        parser_version="2.4.0",
        parser_component_version="2.4.0",
    )
    store = EngineStore(tmp_path / "data", Trust("stable", {}), engine, probe=probe)
    return store


def wheel_file(tmp_path, version="2.5.0"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        bundle.writestr("parsehub/__init__.py", "# upstream unchanged")
        prefix = f"parsehub-{version}.dist-info/"
        bundle.writestr(prefix + "METADATA", f"Name: parsehub\nVersion: {version}\n")
        bundle.writestr(prefix + "WHEEL", "Root-Is-Purelib: true\nTag: py3-none-any\n")
    data = stream.getvalue()
    filename = f"parsehub-{version}-py3-none-any.whl"
    wheel = OfficialWheel(
        version,
        filename,
        "https://files.pythonhosted.org/packages/ab/" + filename,
        hashlib.sha256(data).hexdigest(),
        len(data),
        ">=3.12",
    )
    path = tmp_path / filename
    path.write_bytes(data)
    return path, wheel


def test_original_wheel_switch_restart_and_rollback(tmp_path):
    store = environment(tmp_path)
    path, wheel = wheel_file(tmp_path)
    name, engine = install(store, wheel, path)
    assert store.state()["current"] == "bundled"
    assert engine.program == store.bundled.program
    assert engine.parser_version == engine.version == "2.5.0"
    assert "--official-package-dir" in engine.arguments
    store.begin(name)
    # Interrupted activation recovers the old engine.
    assert store.recover() == store.bundled
    store.begin(name)
    store.confirm(name)
    assert store.recover() == engine
    assert store.active_runtime() == ("bundled", store.bundled)
    store.begin("bundled")
    store.confirm("bundled")
    assert store.recover() == store.bundled


def test_tampering_after_validation_is_rejected_before_start(tmp_path):
    store = environment(tmp_path)
    path, wheel = wheel_file(tmp_path)
    name, _ = install(store, wheel, path)
    store.begin(name)
    store.confirm(name)
    package = store.root / "engines" / name / "python/parsehub/__init__.py"
    package.write_text("# tampered")
    with pytest.raises(ValueError):
        store.installed(name)
    assert store.recover() == store.bundled


def test_failed_probe_cannot_change_selection(tmp_path):
    def reject(*_, **__):
        raise ValueError("incompatible upstream API")

    store = environment(tmp_path, probe=reject)
    path, wheel = wheel_file(tmp_path)
    with pytest.raises(ValueError):
        install(store, wheel, path)
    assert store.recover() == store.bundled


def test_downgrade_and_incompatible_runtime_do_not_install(tmp_path):
    store = environment(tmp_path)
    path, wheel = wheel_file(tmp_path, "2.3.0")
    with pytest.raises(UpdateError) as error:
        install(store, wheel, path)
    assert error.value.code == "UPDATE_DOWNGRADE"
    (tmp_path / "runtime/engine.json").write_text("{}")
    with pytest.raises(UpdateError) as error:
        install(store, wheel, path)
    assert error.value.code == "OFFICIAL_RUNTIME_REQUIRED"
    assert store.recover() == store.bundled
