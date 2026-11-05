"""Export reviewed local source/test deltas as independently hash-pinned patches."""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from pathlib import Path

from media_downloader import UPSTREAM_SHA

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "0001-transfers.patch": ["src/parsehub/utils/downloader.py", "src/parsehub/types/result.py"],
    "0002-tools.patch": ["src/parsehub/errors.py", "src/parsehub/parsers/base/ytdlp.py"],
    "0003-platform-boundary.patch": [
        "src/parsehub/__init__.py",
        "src/parsehub/parsers/base/base.py",
        "src/parsehub/parsers/parser/__init__.py",
        "src/parsehub/parsers/parser/bilibili.py",
        "src/parsehub/parsers/parser/wxchannels.py",
        "src/parsehub/provider_api/bilibili.py",
        "src/parsehub/provider_api/kuaishou.py",
        "src/parsehub/utils/fallback.py",
    ],
    "0004-windows-tests.patch": [
        "test/test_bilibili_offline.py",
        "test/test_cli.py",
        "test/test_cli_config.py",
    ],
    "0005-lightweight-metadata.patch": ["pyproject.toml", "src/parsehub/utils/media_info.py"],
}


def main():
    repository = ROOT / ".cache/upstream-baseline"
    output = ROOT / "patches/parsehub"
    output.mkdir(parents=True, exist_ok=True)
    work = ROOT / "build/patch-export" / uuid.uuid4().hex
    records = []
    for name, paths in GROUPS.items():
        directory = work / name.removesuffix(".patch")
        for relative in paths:
            original = subprocess.check_output(
                ["git", "-C", str(repository), "show", f"{UPSTREAM_SHA}:{relative}"]
            )
            patched = (ROOT / "upstream-ParseHub" / relative).read_bytes()
            for prefix, data in (("a", original), ("b", patched)):
                target = directory / prefix / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data.replace(b"\r\n", b"\n").rstrip(b"\n") + b"\n")
        result = subprocess.run(
            ["git", "diff", "--no-index", "--binary", "--src-prefix=", "--dst-prefix=", "--", "a", "b"],
            cwd=directory,
            capture_output=True,
        )
        if result.returncode not in {0, 1}:
            raise RuntimeError("Patch export failed")
        if result.stdout:
            (output / name).write_bytes(result.stdout)
            records.append(
                {"file": name, "sha256": hashlib.sha256(result.stdout).hexdigest(), "paths": paths}
            )
    (output / "patchset.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "base_sha": UPSTREAM_SHA,
                "patches": records,
                "excluded": {"uv.lock": "Original upstream lock preserved in Git; the app owns root uv.lock"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"patches": len(records), "base_sha": UPSTREAM_SHA}))


if __name__ == "__main__":
    main()
