"""Load a verified ParseHub component using an unchanged frozen worker runtime."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import tomllib
from pathlib import Path

from . import PROTOCOL


def runtime_id(lock: Path) -> str:
    packages = tomllib.loads(lock.read_text(encoding="utf-8"))["package"]
    by_name = {p["name"]: p for p in packages}
    required = set(by_name)
    if "media-downloader-windows" in by_name:
        required = set()
        # Only the worker dependency closure participates; Qt belongs to the task service.
        pending = [("parsehub", ("cli",)), ("cryptography", ()), ("packaging", ())]
        visited = set()
        while pending:
            name, extras = pending.pop()
            if (name, extras) in visited:
                continue
            visited.add((name, extras))
            required.add(name)
            package = by_name[name]
            dependencies = list(package.get("dependencies", []))
            for extra in extras:
                dependencies.extend(package.get("optional-dependencies", {}).get(extra, []))
            pending.extend((item["name"], tuple(item.get("extra", []))) for item in dependencies)
    dependencies = sorted(
        (p["name"], p["version"])
        for p in packages
        if p["name"] in required and "registry" in p.get("source", {})
    )
    contract = {
        "loader_abi": 2,
        "python_abi": "cp312",
        "target": "windows-x86_64",
        "protocol": PROTOCOL,
        "dependencies": dependencies,
    }
    return "rt1-" + hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()[:24]


def activate(directory: Path, runtime_descriptor: Path):
    from .update_archive import no_reparse

    no_reparse(directory)
    no_reparse(runtime_descriptor)
    metadata = json.loads((directory / "engine.json").read_bytes())
    runtime = json.loads(runtime_descriptor.read_bytes())
    if (
        metadata.get("component") != "parsehub"
        or metadata.get("protocol") != PROTOCOL
        or metadata.get("target") != "windows-x86_64"
        or not re.fullmatch(r"rt1-[0-9a-f]{24}", metadata.get("requires_runtime_id", ""))
        or metadata["requires_runtime_id"] != runtime.get("runtime_id")
    ):
        raise ValueError("ParseHub component requires a different runtime")
    code = directory / "python"
    no_reparse(code / "parsehub/__init__.py")
    if not (code / "parsehub/__init__.py").is_file():
        raise ValueError("Missing ParseHub component entry point")
    if any(name == "parsehub" or name.startswith("parsehub.") for name in sys.modules):
        raise ValueError("ParseHub was loaded before component selection")
    sys.dont_write_bytecode = True  # Installed component inventories must remain immutable.
    # The update store has authenticated and inventory-checked these bytes before
    # starting the worker. Precedence is set before any ParseHub module is imported.
    sys.path.insert(0, str(code.resolve()))
    import media_downloader

    media_downloader.UPSTREAM_SHA = metadata["upstream_sha"]
    media_downloader.ENGINE_VERSION = metadata["engine_version"]
    import parsehub

    if not Path(parsehub.__file__).resolve().is_relative_to(code.resolve()):
        raise ValueError("ParseHub component was shadowed by another package")
    if metadata.get("adapter_abi") is not None:
        if metadata["adapter_abi"] != 1 or runtime.get("parser_adapter_abi") != 1:
            raise ValueError("Incompatible ParseHub adapter ABI")
        name = "media_downloader.adapter"
        if name in sys.modules:
            raise ValueError("Adapter was loaded before component selection")
        adapter = directory / "adapter/adapter.py"
        no_reparse(adapter)
        if not adapter.is_file():
            raise ValueError("Missing parser adapter")
        spec = importlib.util.spec_from_file_location(name, adapter)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return metadata
