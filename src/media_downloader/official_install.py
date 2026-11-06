"""Immutable upstream wheel installation composed with an authenticated runtime.

The original wheel is retained and rechecked on every application start. Selection
uses the same pending/confirmed state and idle worker switch as runtime updates.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, replace
from pathlib import Path

from packaging.version import Version

from .official_packages import OfficialWheel, extract_wheel, inspect_wheel, wheel_from_metadata
from .task_files import atomic_json
from .update_archive import no_reparse
from .update_contracts import fail, strict_json


def runtime_contract(runtime):
    if runtime.components:
        from .execution_profile import descriptor

        return descriptor(runtime.components["python-runtime"], "python-runtime")["contract"]
    path = Path(runtime.program).parent / "engine.json"
    no_reparse(path)
    if path.stat().st_size > 1024**2:
        raise ValueError("Oversize runtime descriptor")
    data = strict_json(path.read_bytes())
    contract = data.get("official_package_runtime")
    if not contract or contract.get("adapter_abi") != 1:
        fail("OFFICIAL_RUNTIME_REQUIRED", "请先安装支持官方原包的执行环境，再独立更新 ParseHub。")
    return contract


def identity(wheel):
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", wheel.version):
        raise ValueError("Unsupported upstream version")
    return f"pypi-{wheel.version}-{wheel.sha256[:12]}"


def checked_receipt(data):
    wheel = OfficialWheel(**data["wheel"])
    # Reuse the fixed upstream origin and stable-wheel checks for saved receipts.
    metadata = {
        "info": {"name": "parsehub", "version": wheel.version},
        "urls": [
            {
                "filename": wheel.filename,
                "url": wheel.url,
                "size": wheel.size,
                "digests": {"sha256": wheel.sha256},
                "requires_python": wheel.requires_python,
                "packagetype": "bdist_wheel",
                "yanked": False,
            }
        ],
    }
    if data.get("schema") != 1 or wheel_from_metadata(json.dumps(metadata).encode()) != wheel:
        raise ValueError("Invalid official package receipt")
    return wheel


def compose(runtime, directory, wheel):
    runtime_contract(runtime)
    return replace(
        runtime,
        version=wheel.version,
        upstream_sha=wheel.sha256,
        arguments=(*runtime.arguments, "--official-package-dir", str((directory / "python").resolve())),
        parser_version=wheel.version,
        parser_component_version=wheel.version,
        component="parsehub",
    )


def installed(store, name, *, require_healthy=True, runtime_only=False):
    if runtime_only or not re.fullmatch(r"pypi-\d+(?:\.\d+){1,3}-[0-9a-f]{12}", name):
        fail("UPDATE_STATE", "官方解析包版本指针无效。")
    directory = store.root / "engines" / name
    no_reparse(directory)
    receipt_path = directory / "official-wheel.json"
    no_reparse(receipt_path)
    if receipt_path.stat().st_size > 8192:
        raise ValueError("Oversize official package receipt")
    receipt = strict_json(receipt_path.read_bytes())
    wheel = checked_receipt(receipt)
    if identity(wheel) != name:
        raise ValueError("Official package pointer mismatch")
    runtime = store.installed(store.runtime_reference(name), runtime_only=True)
    contract = runtime_contract(runtime)
    if receipt["runtime_id"] != runtime.runtime_id:
        fail("OFFICIAL_RUNTIME_REQUIRED", "官方解析包与当前执行环境不匹配。")
    inventory = inspect_wheel(directory / wheel.filename, wheel, contract)
    package = directory / "python"
    actual = set()
    for file in package.rglob("*"):
        no_reparse(file)
        if file.is_file():
            relative = file.relative_to(package).as_posix()
            actual.add(relative)
            with file.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if inventory.get(relative) != digest:
                raise ValueError("Installed ParseHub differs from upstream wheel")
    if actual != set(inventory):
        raise ValueError("Incomplete official package installation")
    if require_healthy:
        marker = directory / "healthy.json"
        no_reparse(marker)
        if (
            marker.stat().st_size > 4096
            or strict_json(marker.read_bytes()).get("wheel_sha256") != wheel.sha256
        ):
            fail("UPDATE_HEALTH", "官方解析包尚未通过自检。")
    return compose(runtime, directory, wheel)


def install(store, wheel, archive, *, cancelled=lambda: False):
    from .update_store import update_lock

    with update_lock(store.root):
        reference, runtime = store.active_runtime()
        contract = runtime_contract(runtime)
        current = store.installed(store.state()["current"])
        if current.parser_version and Version(wheel.version) <= Version(current.parser_version):
            fail("UPDATE_DOWNGRADE", "官方解析包不高于当前版本，未执行替换。")
        name = identity(wheel)
        target = store.root / "engines" / name
        no_reparse(target)
        if target.exists():
            engine = installed(store, name, require_healthy=False)
            if not (target / "healthy.json").exists():
                store.probe(engine, cancelled=cancelled)
                installed(store, name, require_healthy=False)
                if cancelled():
                    fail("UPDATE_CANCELLED", "解析组件更新已取消。")
                atomic_json(target / "healthy.json", {"wheel_sha256": wheel.sha256})
            return name, installed(store, name)
        stage = store.root / "updates" / "staging" / uuid.uuid4().hex
        no_reparse(stage)
        stage.mkdir(parents=True)
        extract_wheel(archive, wheel, contract, stage / "python", cancelled=cancelled)
        # Only verified archive bytes enter the receipt directory.
        (stage / wheel.filename).write_bytes(Path(archive).read_bytes())
        atomic_json(
            stage / "official-wheel.json",
            {
                "schema": 1,
                "wheel": asdict(wheel),
                "runtime_id": runtime.runtime_id,
            },
        )
        atomic_json(stage / "runtime-reference.json", {"runtime": reference})
        if cancelled():
            fail("UPDATE_CANCELLED", "解析组件更新已取消。")
        target.parent.mkdir(parents=True, exist_ok=True)
        no_reparse(target.parent)
        os.rename(stage, target)
        engine = installed(store, name, require_healthy=False)
        store.probe(engine, cancelled=cancelled)
        # Reject package writes made by imports or a faulty candidate probe.
        installed(store, name, require_healthy=False)
        if cancelled():
            fail("UPDATE_CANCELLED", "解析组件更新已取消。")
        atomic_json(target / "healthy.json", {"wheel_sha256": wheel.sha256})
        return name, installed(store, name)
