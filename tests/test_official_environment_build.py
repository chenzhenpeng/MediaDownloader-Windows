import hashlib
import zipfile

import pytest
from scripts.build_official_environment import build

from media_downloader.official_paths import candidate_python
from media_downloader.update_contracts import UpdateError


def archive_at(tmp_path, *, extra=None):
    archive = tmp_path / "python.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("python.exe", b"fixture-not-executed")
        bundle.writestr("python312.zip", b"fixture-stdlib")
        bundle.writestr("python312._pth", "python312.zip\n.\n")
        if extra:
            bundle.writestr(extra, b"unexpected")
    requirements = tmp_path / "locked.txt"
    requirements.write_text("parsehub==2.4.0\n")
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest(), requirements


def test_assembly_uses_explicit_offline_target_and_isolated_paths(tmp_path, monkeypatch):
    archive, digest, requirements = archive_at(tmp_path)
    calls = []
    monkeypatch.setattr(
        "scripts.build_official_environment.subprocess.run",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )
    output = tmp_path / "candidate"
    build(archive, digest, requirements, output)
    assert candidate_python(output) == output / "python.exe"
    assert (output / "python312._pth").read_text().splitlines() == ["python312.zip", ".", "Lib/site-packages"]
    assert "--offline" in calls[0][0] and "--target" in calls[0][0]
    assert calls[0][1]["check"] is True
    with pytest.raises(ValueError, match="already exists"):
        build(archive, digest, requirements, output)


def test_digest_mismatch_cannot_create_output(tmp_path):
    archive, _, requirements = archive_at(tmp_path)
    output = tmp_path / "candidate"
    with pytest.raises(ValueError, match="digest"):
        build(archive, "0" * 64, requirements, output)
    assert not output.exists()


def test_archive_traversal_cannot_escape_candidate(tmp_path):
    archive, digest, requirements = archive_at(tmp_path, extra="../escape")
    with pytest.raises(UpdateError):
        build(archive, digest, requirements, tmp_path / "candidate")
    assert not (tmp_path / "escape").exists()


def test_ambiguous_interpreter_is_rejected(tmp_path):
    (tmp_path / "python.exe").write_bytes(b"fixture")
    (tmp_path / "Scripts").mkdir()
    (tmp_path / "Scripts/python.exe").write_bytes(b"fixture")
    with pytest.raises(ValueError, match="ambiguous"):
        candidate_python(tmp_path)
