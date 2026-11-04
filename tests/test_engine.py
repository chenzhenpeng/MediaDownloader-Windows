import json

import pytest

from media_downloader import PROTOCOL, UPSTREAM_SHA
from media_downloader.engine import resolve_engine


def test_local_engine_versions_are_isolated(tmp_path):
    for name in ("e1", "e2"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "media-engine.exe").write_bytes(b"test descriptor, not a runnable executable")
        (directory / "engine.json").write_text(
            json.dumps(
                {
                    "protocol": PROTOCOL,
                    "target": "windows-x86_64",
                    "engine_version": name,
                    "upstream_sha": UPSTREAM_SHA,
                }
            ),
            encoding="utf-8",
        )
        assert resolve_engine(directory).version == name
    assert resolve_engine(tmp_path / "e1").program != resolve_engine(tmp_path / "e2").program


@pytest.mark.parametrize("protocol,target", [(999, "windows-x86_64"), (PROTOCOL, "linux-x86_64")])
def test_incompatible_engine_is_rejected(tmp_path, protocol, target):
    (tmp_path / "engine.json").write_text(
        json.dumps({"protocol": protocol, "target": target}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Incompatible"):
        resolve_engine(tmp_path)
