# MediaDownloader Windows

Windows x64 media downloader based on [ParseHub](https://github.com/z-mio/ParseHub), with a native WinUI 3 interface and an isolated task/worker architecture.

The application package, ParseHub parser component, and execution runtime have separate release boundaries. Read [component architecture and publication](docs/components.md) for the current implementation. Published downloads are listed in [GitHub Releases](https://github.com/chenzhenpeng/MediaDownloader-Windows/releases); a local development build does not imply a public release.

## Windows application

The main installer is a native x64 EXE with current-user installation. Close the application before upgrading. Settings, encrypted credentials, task history and downloaded files are retained. Preview installers do not yet have a product code-signing certificate. The optional MSI is a separate legacy/deployment path.

The interface supports Windows themes, encrypted per-platform Cookie storage with masked readback, per-post folders, and one download management page. The platform catalog describes parser capabilities; availability and accepted media types vary by platform.

## Development

Windows x64, Python 3.12, uv and the .NET SDK pinned in `native/global.json` are required.

```powershell
uv sync --locked
uv run pytest tests upstream-ParseHub/test -q --tb=short
uv run ruff check src tests scripts packaging
```

Application, parser and execution-runtime build workflows are under `.github/workflows`. The application workflow consumes an authenticated runtime rather than rebuilding ParseHub for each UI release. Media tools and the portable installer compiler use reviewed SHA-256 locks.

## Updates

New clients use the signed fixed `channel-stable` component catalog rather than repository Latest. Normal updates require a newer compatible component. Parser updates reuse an authenticated matching runtime; pointer changes represent complete version combinations and preserve a known-good rollback. Old clients retain the previous full-engine discovery path.

Upstream polling prepares candidate PRs and replays reviewed patches. It does not automatically execute or publish arbitrary upstream changes. Release workflows create drafts for acceptance. Signing runs in the protected `engine-release` environment; private keys and user Cookies are never committed.

## Documentation and licensing

[Component architecture](docs/components.md) | [Development plan](docs/development-plan.md) | [Patch maintenance](docs/upstream-patches.md) | [Platform coverage](docs/platforms-integration.md)

Vendored ParseHub retains its [MIT license](upstream-ParseHub/LICENSE). Bundled third-party components retain their respective licenses. Older Qt notes are preserved in [legacy notes](docs/legacy-qt-readme.md).

## Original-package migration

Preview 13 keeps the accepted production engine. The direct official ParseHub package path has passed isolated task-service validation but is still explicitly experimental; see [migration status](docs/official-package-status.md). Updating the source repository does not enable this path in installed clients.
