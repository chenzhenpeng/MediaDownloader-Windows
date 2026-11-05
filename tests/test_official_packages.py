import hashlib
import io
import json
import zipfile
from dataclasses import replace

import httpx
import pytest

from media_downloader.official_packages import (
    OfficialWheel,
    check_latest,
    download_wheel,
    extract_wheel,
    inspect_wheel,
    wheel_from_metadata,
)
from media_downloader.update_contracts import UpdateError


def artifact(*, requires="demo>=2", extra=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        bundle.writestr("parsehub/__init__.py", "# upstream bytes\n")
        bundle.writestr(
            "parsehub-2.4.0.dist-info/METADATA",
            (
                "Metadata-Version: 2.4\nName: parsehub\nVersion: 2.4.0\nRequires-Python: >=3.12\n"
                f"Requires-Dist: {requires}\n"
            ),
        )
        bundle.writestr(
            "parsehub-2.4.0.dist-info/WHEEL",
            ("Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"),
        )
        if extra:
            bundle.writestr(extra, "unexpected")
    payload = stream.getvalue()
    wheel = OfficialWheel(
        "2.4.0",
        "parsehub-2.4.0-py3-none-any.whl",
        "https://files.pythonhosted.org/packages/ab/parsehub-2.4.0-py3-none-any.whl",
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        ">=3.12",
    )
    return payload, wheel


def metadata(wheel):
    return {
        "info": {"name": "parsehub", "version": wheel.version},
        "urls": [
            {
                "filename": wheel.filename,
                "url": wheel.url,
                "digests": {"sha256": wheel.sha256},
                "size": wheel.size,
                "packagetype": "bdist_wheel",
                "requires_python": wheel.requires_python,
            }
        ],
    }


RUNTIME = {
    "python": "3.12.12",
    "marker_environment": {"sys_platform": "win32"},
    "dependencies": {"demo": "2.1"},
}


def test_only_official_universal_stable_wheel_is_selected():
    _, wheel = artifact()
    raw = metadata(wheel)
    assert wheel_from_metadata(json.dumps(raw).encode()) == wheel
    for url in (
        "http://files.pythonhosted.org/packages/x.whl",
        "https://evil.example/a.whl",
        wheel.url + "?secret=1",
        "https://user@files.pythonhosted.org/packages/a.whl",
    ):
        raw["urls"][0]["url"] = url
        with pytest.raises(ValueError):
            wheel_from_metadata(json.dumps(raw).encode())


@pytest.mark.parametrize(
    "change",
    [
        {"yanked": True},
        {"size": True},
        {"size": 20 * 1024**2},
        {"digests": {"sha256": "invalid"}},
        {"filename": "other-2.4.0-py3-none-any.whl"},
    ],
)
def test_invalid_release_is_rejected(change):
    _, wheel = artifact()
    raw = metadata(wheel)
    raw["urls"][0].update(change)
    with pytest.raises(ValueError):
        wheel_from_metadata(json.dumps(raw).encode())


def test_metadata_and_wheel_use_exact_hosts_without_redirects(tmp_path):
    payload, wheel = artifact()
    requests = []

    def serve(request):
        requests.append(str(request.url))
        if request.url.host == "pypi.org":
            return httpx.Response(200, json=metadata(wheel))
        return httpx.Response(200, content=payload)

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        found = check_latest(client=client)
        path = download_wheel(found, tmp_path / found.filename, client=client)
    assert path.read_bytes() == payload
    assert requests == ["https://pypi.org/pypi/parsehub/json", wheel.url]
    files = extract_wheel(path, wheel, RUNTIME, tmp_path / "extracted")
    assert files["parsehub/__init__.py"] == hashlib.sha256(b"# upstream bytes\n").hexdigest()


def test_hash_failure_and_cancellation_leave_no_download(tmp_path):
    payload, wheel = artifact()
    path = tmp_path / "download.whl"
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=payload))
    ) as client:
        with pytest.raises(ValueError):
            download_wheel(replace(wheel, sha256="0" * 64), path, client=client)
        assert not path.exists()
        with pytest.raises(UpdateError, match="取消"):
            download_wheel(wheel, path, client=client, cancelled=lambda: True)
        assert not path.exists()
        path.write_bytes(b"user-owned")
        with pytest.raises(FileExistsError):
            download_wheel(wheel, path, client=client)
        assert path.read_bytes() == b"user-owned"


@pytest.mark.parametrize(
    "entry",
    [
        "../escape.py",
        "parsehub/../../escape",
        "other/__init__.py",
        "parsehub-2.4.0.data/scripts/run.exe",
        "PARSEHUB/__init__.py",
    ],
)
def test_archive_escape_and_unexpected_packages_never_extract(tmp_path, entry):
    payload, wheel = artifact(extra=entry)
    path = tmp_path / wheel.filename
    path.write_bytes(payload)
    with pytest.raises((ValueError, UpdateError)):
        extract_wheel(path, wheel, RUNTIME, tmp_path / "target")
    assert not (tmp_path / "target").exists()


@pytest.mark.parametrize("requires", ["demo>=3", "missing>=1", "demo @ https://example.com/a.whl"])
def test_changed_dependencies_require_runtime_update_before_import(tmp_path, requires):
    payload, wheel = artifact(requires=requires)
    path = tmp_path / wheel.filename
    path.write_bytes(payload)
    with pytest.raises(UpdateError) as error:
        inspect_wheel(path, wheel, RUNTIME)
    assert error.value.code == "OFFICIAL_RUNTIME_REQUIRED"


def test_windows_markers_and_optional_dependencies_are_respected(tmp_path):
    payload, wheel = artifact(requires='missing>=1; sys_platform == "linux"')
    path = tmp_path / wheel.filename
    path.write_bytes(payload)
    assert inspect_wheel(path, wheel, RUNTIME)
    with pytest.raises(UpdateError):
        inspect_wheel(path, wheel, {**RUNTIME, "python": "3.11.9"})
