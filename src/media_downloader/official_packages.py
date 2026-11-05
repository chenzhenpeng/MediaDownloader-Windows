"""Acquire unmodified ParseHub wheels from PyPI, without running an installer.

PyPI HTTPS metadata supplies the artifact digest; this is upstream transport
trust, not our release signing key. Dependency changes require a new runtime.
"""

from __future__ import annotations

import hashlib
import re
import stat
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

from .update_archive import no_reparse, safe_relative
from .update_contracts import fail, strict_json

PYPI_METADATA = "https://pypi.org/pypi/parsehub/json"
MAX_WHEEL = 16 * 1024**2
MAX_EXPANDED = 64 * 1024**2


@dataclass(frozen=True)
class OfficialWheel:
    version: str
    filename: str
    url: str
    sha256: str
    size: int
    requires_python: str


def wheel_from_metadata(raw: bytes) -> OfficialWheel:
    if len(raw) > 4 * 1024**2:
        raise ValueError("Oversize upstream metadata")
    data = strict_json(raw)
    if canonicalize_name(data["info"]["name"]) != "parsehub":
        raise ValueError("Unexpected upstream project")
    version = Version(data["info"]["version"])
    if version.is_prerelease or version.is_devrelease or version.local or version.epoch:
        raise ValueError("Only stable upstream versions are accepted")
    candidates = []
    for item in data["urls"]:
        if item.get("yanked") or item.get("packagetype") != "bdist_wheel":
            continue
        name, release, _, tags = parse_wheel_filename(item["filename"])
        if name != "parsehub" or release != version:
            raise ValueError("Wheel identity differs from upstream release")
        if not any(str(tag) == "py3-none-any" for tag in tags):
            continue
        url = urlsplit(item["url"])
        digest = item["digests"]["sha256"]
        size = item["size"]
        if (
            url.scheme != "https"
            or url.hostname != "files.pythonhosted.org"
            or url.port not in {None, 443}
            or url.username
            or url.password
            or url.query
            or url.fragment
            or not url.path.startswith("/packages/")
            or url.path.rsplit("/", 1)[-1] != item["filename"]
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or type(size) is not int
            or not 0 < size <= MAX_WHEEL
        ):
            raise ValueError("Invalid upstream wheel artifact")
        requirement = item.get("requires_python") or data["info"].get("requires_python") or ""
        SpecifierSet(requirement)
        candidates.append(
            OfficialWheel(str(version), item["filename"], item["url"], digest, size, requirement)
        )
    if len(candidates) != 1:
        raise ValueError("Missing or ambiguous universal wheel")
    return candidates[0]


def _cancel(cancelled):
    if cancelled():
        fail("UPDATE_CANCELLED", "解析组件更新已取消，当前版本未更改。")


def check_latest(*, client=None, cancelled=lambda: False):
    _cancel(cancelled)
    if client is None:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as connection:
            return check_latest(client=connection, cancelled=cancelled)
    raw = bytearray()
    with client.stream("GET", PYPI_METADATA, headers={"User-Agent": "MediaDownloader-Windows"}) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            _cancel(cancelled)
            raw.extend(chunk)
            if len(raw) > 4 * 1024**2:
                raise ValueError("Oversize upstream metadata")
    return wheel_from_metadata(bytes(raw))


def download_wheel(
    wheel, destination: Path, *, client=None, cancelled=lambda: False, progress=lambda *_: None
):
    """Write only a new owned file. Never run pip, setup.py or upstream code."""
    if client is None:
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as connection:
            return download_wheel(
                wheel, destination, client=connection, cancelled=cancelled, progress=progress
            )
    no_reparse(destination)
    digest, written = hashlib.sha256(), 0
    created = False
    try:
        _cancel(cancelled)
        with destination.open("xb") as output:
            created = True
            with client.stream("GET", wheel.url) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    _cancel(cancelled)
                    written += len(chunk)
                    if written > wheel.size:
                        raise ValueError("Upstream artifact exceeds declared size")
                    digest.update(chunk)
                    output.write(chunk)
                    progress(written, wheel.size)
        _cancel(cancelled)
        if written != wheel.size or digest.hexdigest() != wheel.sha256:
            raise ValueError("Upstream artifact hash or size mismatch")
        return destination
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def inspect_wheel(path: Path, wheel: OfficialWheel, runtime: dict):
    """Validate the entire wheel and installed runtime before any code is imported."""
    no_reparse(path)
    if (
        path.stat().st_size != wheel.size
        or hashlib.file_digest(path.open("rb"), "sha256").hexdigest() != wheel.sha256
    ):
        raise ValueError("Wheel integrity mismatch")
    prefix = f"parsehub-{wheel.version}.dist-info/"
    with zipfile.ZipFile(path) as archive:
        seen, total = set(), 0
        entries = archive.infolist()
        if not 1 <= len(entries) <= 3000:
            raise ValueError("Invalid wheel file count")
        for info in entries:
            safe_relative(info.filename)
            kind = stat.S_IFMT(info.external_attr >> 16)
            if (
                info.filename.casefold() in seen
                or info.flag_bits & 1
                or kind not in {0, stat.S_IFREG, stat.S_IFDIR}
                or info.external_attr & 0x400
                or not (
                    info.filename.startswith("parsehub/")
                    or info.filename.startswith(prefix)
                    or info.filename == "__init__.py"
                )
            ):
                raise ValueError("Unexpected or linked wheel entry")
            seen.add(info.filename.casefold())
            total += info.file_size
            if total > MAX_EXPANDED:
                raise ValueError("Wheel expands beyond limit")
        if "parsehub/__init__.py" not in seen:
            raise ValueError("Missing ParseHub package")
        metadata = BytesParser().parsebytes(archive.read(prefix + "METADATA"))
        identity = BytesParser().parsebytes(archive.read(prefix + "WHEEL"))
        if (
            canonicalize_name(metadata["Name"]) != "parsehub"
            or Version(metadata["Version"]) != Version(wheel.version)
            or identity["Root-Is-Purelib"] != "true"
            or "py3-none-any" not in identity.get_all("Tag", [])
        ):
            raise ValueError("Wheel metadata identity mismatch")
        python = runtime["python"]
        if not SpecifierSet(wheel.requires_python).contains(python) or not SpecifierSet(
            metadata.get("Requires-Python", "")
        ).contains(python):
            fail("OFFICIAL_RUNTIME_REQUIRED", "官方 ParseHub 需要不同版本的 Python，请先更新执行环境。")
        environment = default_environment()
        environment.update(runtime["marker_environment"])
        environment["extra"] = ""
        dependencies = {canonicalize_name(k): v for k, v in runtime["dependencies"].items()}
        for text in metadata.get_all("Requires-Dist", []):
            requirement = Requirement(text)
            if requirement.marker and not requirement.marker.evaluate(environment):
                continue
            installed = dependencies.get(canonicalize_name(requirement.name))
            extras = set(runtime.get("extras", {}).get(canonicalize_name(requirement.name), []))
            if (
                requirement.url
                or not requirement.extras.issubset(extras)
                or not installed
                or not requirement.specifier.contains(installed, prereleases=True)
            ):
                fail("OFFICIAL_RUNTIME_REQUIRED", "官方 ParseHub 的依赖已变化，请先更新执行环境。")
        return {
            info.filename: hashlib.sha256(archive.read(info)).hexdigest()
            for info in entries
            if not info.is_dir()
        }


def extract_wheel(path, wheel, runtime, target, *, cancelled=lambda: False):
    inventory = inspect_wheel(path, wheel, runtime)
    no_reparse(target)
    target.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(path) as archive:
        for name in inventory:
            _cancel(cancelled)
            destination = target.joinpath(*safe_relative(name))
            no_reparse(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(name))
    return inventory
