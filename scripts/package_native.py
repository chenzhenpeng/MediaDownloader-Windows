"""Archive only the native distribution; never include local test data or credentials."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "dist/native/MediaDownloader"
    required = [
        "MediaDownloader.exe",
        "MediaDownloader.pri",
        "MainWindow.xbf",
        "App.xbf",
        "backend/MediaBackend.exe",
        "engine/media-engine.exe",
        "engine/engine.json",
    ]
    assert all((directory / name).is_file() for name in required)
    readme = (
        "Media Downloader 0.2.0.dev13 - WinUI 3 原生界面预览版\n\n"
        "请完整解压后运行 MediaDownloader/MediaDownloader.exe。无需单独安装 .NET。\n"
        "请先关闭旧客户端；新旧版本使用同一任务数据目录，不能同时运行。\n"
        "保留 backend、engine、Assets、PRI、XBF 和所有运行库文件。\n"
        "本包未签名，属于本地测试包；已配置受信任的 GitHub 内核签名更新源。\n"
        "按平台与作品归档的下载规则、已有任务和内核更新机制继续保留。\n"
    )
    archive = ROOT / "dist/native/MediaDownloader-NATIVE.zip"
    files = sorted(p for p in directory.rglob("*") if p.is_file())
    assert not any(p.suffix in {".sqlite3", ".db"} for p in files)
    with zipfile.ZipFile(
        archive.with_suffix(".zip.part"), "w", zipfile.ZIP_DEFLATED, compresslevel=3
    ) as output:
        for path in files:
            output.write(path, "MediaDownloader/" + path.relative_to(directory).as_posix())
        output.writestr("README.txt", readme)
        output.write(ROOT / "native/README.md", "NATIVE-DESIGN.md")
    archive.with_suffix(".zip.part").replace(archive)
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {
        "artifact": str(archive.relative_to(ROOT)),
        "client": "0.2.0.dev13",
        "engine": "0.1.0.localized-dev12",
        "sha256": digest,
        "zip_bytes": archive.stat().st_size,
        "files": len(files),
        "signed": False,
    }
    (ROOT / "review/native/artifact.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()



