# MediaDownloader Windows

Windows x64 media downloader based on [ParseHub](https://github.com/z-mio/ParseHub), with a native WinUI 3 interface and an isolated task/worker architecture.

The application package, ParseHub parser component, and execution runtime have separate release boundaries. Read [component architecture and publication](docs/components.md) for the current implementation. Published downloads are listed in [GitHub Releases](https://github.com/chenzhenpeng/MediaDownloader-Windows/releases); a local development build does not imply a public release.

## Windows application

The main installer is a native x64 EXE with current-user installation. Close the application before upgrading. Version 0.3 starts a new data baseline under LocalAppData/MediaDownloader/v6. Older settings, credentials and task history are not migrated; existing files are left untouched. Preview installers do not yet have a product code-signing certificate.

The interface supports Windows themes, encrypted per-platform Cookie storage with masked readback, per-post folders, and one download management page. The platform catalog describes parser capabilities; availability and accepted media types vary by platform.

## Development

Windows x64, Python 3.12, uv and the .NET SDK pinned in `native/global.json` are required.

```powershell
uv sync --locked
uv run pytest tests upstream-ParseHub/test -q --tb=short
uv run ruff check src tests scripts packaging
```

Application and independent component build workflows are under `.github/workflows`. The complete installer bundles the components once; subsequent updates download only changed components. Media tools and the installer compiler use reviewed SHA-256 locks.

## Updates

The native client, Worker, official ParseHub wheel, Python dependency environment and FFmpeg/ffprobe tool pair are separate release units. A single immutable execution profile selects a compatible combination. Candidates are verified and probed before an idle atomic switch; interruption and startup failure restore the previous complete combination.

ParseHub keeps its original upstream wheel and version, downloaded directly from official PyPI. Worker, Python and media-tool releases use signed metadata from `channel-components-v1`. No pip, source builds or dependency mutation runs on the user's machine. Python dependencies, including the upstream Python yt-dlp module, remain a complete locked environment.

Settings supports an explicitly selected local x64 FFmpeg/ffprobe directory. Both binaries and required formats are checked; their recorded hashes are rechecked when composing a profile. Online updates do not replace an explicitly chosen local pair, and cleanup never deletes that external directory.

`components-release.yml` builds and signs requested components in GitHub Actions. `application-release.yml` consumes authenticated components and the original SDK. Repository Latest is reserved for the client installer. Old client/data layouts are not migrated. Signing runs in the protected `engine-release` environment; private keys and user Cookies are never committed.

Validation: 393 regression tests passed, with the interactive native/Qt UI test excluded from the headless run. Real acceptance covered a signed Worker-only update of about 33 KiB with large component directories reused, restart recovery, explicit local tools, interrupted-switch rollback, and a complete Kuaishou HLS video through the frozen backend. Initial full-installer size is not expected to fall proportionally: the large environment and media binaries are still needed for offline use.

## Documentation and licensing

[Component architecture](docs/components.md) | [Development plan](docs/development-plan.md) | [Patch maintenance](docs/upstream-patches.md) | [Platform coverage](docs/platforms-integration.md)

Vendored ParseHub retains its [MIT license](upstream-ParseHub/LICENSE). Bundled third-party components retain their respective licenses. Older Qt notes are preserved in [legacy notes](docs/legacy-qt-readme.md).
