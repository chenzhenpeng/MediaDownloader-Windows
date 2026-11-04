# MediaDownloader Windows

Windows x64 media downloader based on [ParseHub](https://github.com/z-mio/ParseHub), with a native WinUI 3 frontend and an isolated Python engine.

Current client: **0.2.0 preview 4**. Navigation combines downloads and history into one management page. Supports Windows themes, per-platform encrypted Cookie storage and masked readback, and per-post download folders.

## Development

Windows x64, Python 3.12 and uv are required. Native SDK requirements are pinned in `native/global.json`.

```powershell
uv sync --locked
uv run pytest tests upstream-ParseHub/test -q --tb=short
uv run ruff check src tests scripts packaging
uv run python scripts/build_native.py
```

The x64 MSI uses WiX 6.0.2 with its UI extension. See `scripts/build_msi.py`. Preview packages are unsigned. When migrating from the previous EXE installer, uninstall that application first; downloaded files and application data are retained.

## Upstream and engine updates

Scheduled Actions detect upstream changes, replay reviewed patches and prepare a draft PR. Validation and review precede merging. A separate manual workflow builds and signs compatible engine packages and creates a draft release.

**Production signing secrets, tool bundle variables and client trust configuration are not yet provisioned. Online engine installation is not enabled merely by creating this repository.** See [release setup](docs/release-setup.md).

The current engine exposes 24 platform entries; online success and media types vary by platform. See [platform coverage](docs/platforms-integration.md).

## Documentation and licensing

[Development plan](docs/development-plan.md) | [Architecture](docs/design.md) | [Engine updates](docs/engine-updates.md) | [Patch maintenance](docs/upstream-patches.md)

Vendored ParseHub retains its [MIT license](upstream-ParseHub/LICENSE). Third-party components retain their respective licenses. Older Qt development notes are preserved in [legacy notes](docs/legacy-qt-readme.md).
