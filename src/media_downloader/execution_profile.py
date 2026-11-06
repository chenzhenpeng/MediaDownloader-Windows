"""Compose independently installed immutable components into one worker process."""

from __future__ import annotations

import re
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from . import PROTOCOL
from .engine import Engine
from .update_archive import no_reparse, safe_relative
from .update_contracts import digest_file, strict_json

KINDS = ("worker", "python-runtime", "parsehub", "media-tools")


def descriptor(directory, kind):
    directory = Path(directory).resolve()
    no_reparse(directory)
    path = directory / "component.json"
    no_reparse(path)
    if path.stat().st_size > 1024**2:
        raise ValueError("Oversize component descriptor")
    data = strict_json(path.read_bytes())
    if data.get("schema") != 1 or data.get("kind") != kind or data.get("target") != "windows-x86_64":
        raise ValueError("Invalid component descriptor")
    Version(data["version"])
    return data


def compose(components):
    if set(components) != set(KINDS):
        raise ValueError("Incomplete execution combination")
    roots = {kind: Path(value).resolve() for kind, value in components.items()}
    metadata = {kind: descriptor(roots[kind], kind) for kind in KINDS}
    worker, python = metadata["worker"], metadata["python-runtime"]
    parser, tools = metadata["parsehub"], metadata["media-tools"]
    tools_root = Path(tools.get("external_directory", roots["media-tools"])).resolve()
    no_reparse(tools_root)
    requirements = worker["requires"]
    if (
        worker["protocol"] != PROTOCOL
        or requirements["environment_abi"] != python["abi"]
        or not SpecifierSet(requirements["python"]).contains(python["python"])
        or not SpecifierSet(requirements["parsehub"]).contains(parser["version"])
        or not SpecifierSet(requirements["media_tools"]).contains(tools["version"])
    ):
        raise ValueError("Incompatible execution components")
    # The same wheel/dependency check is used for bundled and online packages.
    from .official_packages import OfficialWheel, inspect_wheel

    wheel = OfficialWheel(**parser["wheel"])
    inventory = inspect_wheel(roots["parsehub"] / wheel.filename, wheel, python["contract"])
    package = roots["parsehub"] / "python"
    actual = {p.relative_to(package).as_posix(): p for p in package.rglob("*") if p.is_file()}
    if actual.keys() != inventory.keys():
        raise ValueError("Official package inventory mismatch")
    for name, digest in inventory.items():
        no_reparse(actual[name])
        if digest_file(actual[name]) != digest:
            raise ValueError("Official package bytes changed")
    program = roots["python-runtime"] / "python.exe"
    entry = roots["worker"] / "worker_entry.py"
    if not program.is_file() or not entry.is_file():
        raise ValueError("Incomplete Python/worker component")
    for name in ("ffmpeg", "ffprobe"):
        path = tools_root / (name + ".exe")
        no_reparse(path)
        if not path.is_file() or digest_file(path) != tools["files"][path.name]:
            raise ValueError("Media tool bytes changed")
    arguments = ("-B", "-I", str(entry))
    for kind, option in (
        ("python-runtime", "--runtime-dir"),
        ("worker", "--worker-dir"),
        ("parsehub", "--parser-dir"),
        ("media-tools", "--tools-dir"),
    ):
        arguments += (option, str(tools_root if kind == "media-tools" else roots[kind]))
    return Engine(
        version=worker["version"],
        upstream_sha=wheel.sha256,
        program=str(program),
        arguments=arguments,
        runtime_id=python["identity"],
        runtime_version=python["version"],
        parser_version=wheel.version,
        component="profile",
        parser_component_version=wheel.version,
        components={kind: str(path) for kind, path in roots.items()},
        component_versions={kind: item["version"] for kind, item in metadata.items()},
    )


def load_bundle(root):
    path = root / "profile.json"
    if path.stat().st_size > 32768:
        raise ValueError("Oversize bundle profile")
    profile = strict_json(path.read_bytes())
    if profile.get("schema") != 1 or set(profile["components"]) != set(KINDS):
        raise ValueError("Invalid bundle profile")
    roots = {}
    for kind, relative in profile["components"].items():
        parts = safe_relative(relative)
        target = root.joinpath(*parts)
        no_reparse(target)
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError("Component escaped bundle")
        roots[kind] = target
    return compose(roots)


def component_id(kind, version, digest):
    if kind not in KINDS or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid component identity")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}", version):
        raise ValueError("Invalid component version")
    return kind + "-" + version + "-" + digest[:12]
