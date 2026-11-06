import hashlib
import json

import pytest
from scripts import build_windows


def test_build_rejects_external_or_existing_work_directory(monkeypatch, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(build_windows, "ROOT", root)
    with pytest.raises(ValueError, match="inside"):
        build_windows.new_work_directory(tmp_path / "outside")
    work = build_windows.new_work_directory(root / ".local" / "build")
    sentinel = work / "do-not-delete.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        build_windows.new_work_directory(work)
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_compiler_reuse_requires_pinned_digest(monkeypatch, tmp_path):
    monkeypatch.setattr(build_windows, "ROOT", tmp_path)
    config = tmp_path / "packaging/windows/toolchain.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"iscc_sha256": hashlib.sha256(b"trusted").hexdigest()}))
    compiler = tmp_path / ".cache/installer-tools/InnoSetup7/ISCC.exe"
    compiler.parent.mkdir(parents=True)
    compiler.write_bytes(b"trusted")
    assert build_windows.compiler_path() == compiler
    compiler.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="pinned"):
        build_windows.compiler_path()
    assert compiler.read_bytes() == b"tampered"
