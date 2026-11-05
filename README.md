# MediaDownloader Windows

Windows x64 media downloader based on [ParseHub](https://github.com/z-mio/ParseHub), with a native WinUI 3 interface and an isolated task/worker architecture.

The application package, ParseHub parser component, and execution runtime have separate release boundaries. Read [component architecture and publication](docs/components.md) for the current implementation. Published downloads are listed in [GitHub Releases](https://github.com/chenzhenpeng/MediaDownloader-Windows/releases); a local development build does not imply a public release.

## Windows application

The main installer is a native x64 EXE with current-user installation. Close the application before upgrading. Preview 14 uses a fresh official-package baseline under LocalAppData/MediaDownloader/v5. Older settings, credentials and task history are not imported; existing files are left untouched. Preview installers do not yet have a product code-signing certificate.

The interface supports Windows themes, encrypted per-platform Cookie storage with masked readback, per-post folders, and one download management page. The platform catalog describes parser capabilities; availability and accepted media types vary by platform.

## Development

Windows x64, Python 3.12, uv and the .NET SDK pinned in `native/global.json` are required.

```powershell
uv sync --locked
uv run pytest tests upstream-ParseHub/test -q --tb=short
uv run ruff check src tests scripts packaging
```

Application and execution-runtime build workflows are under `.github/workflows`. The application workflow consumes an authenticated runtime; independent parser updates download upstream wheels directly. Media tools and the portable installer compiler use reviewed SHA-256 locks.

## Updates

ParseHub updates download the original stable wheel directly from official PyPI, checking its hash, archive, Python/dependency requirements and worker compatibility before an idle switch. The upstream version is preserved; parser source is not patched or republished. Runtime dependencies remain separate signed GitHub releases through `channel-stable`. Repository Latest points to the current client installer; older client compatibility is not maintained.

Daily client checks and read-only upstream monitoring inspect PyPI. Parser updates reuse a matching execution environment, and dependency changes request a separate runtime update. GitHub Actions can build and sign execution environments without a local build. Signing runs in the protected `engine-release` environment; private keys and user Cookies are never committed.

## Documentation and licensing

[Component architecture](docs/components.md) | [Development plan](docs/development-plan.md) | [Patch maintenance](docs/upstream-patches.md) | [Platform coverage](docs/platforms-integration.md)

Vendored ParseHub retains its [MIT license](upstream-ParseHub/LICENSE). Bundled third-party components retain their respective licenses. Older Qt notes are preserved in [legacy notes](docs/legacy-qt-readme.md).

## Official package baseline

Preview 14 enables the original ParseHub 2.4.0 wheel on a pinned Python 3.13.17 environment. Independent wheel installation, compatibility probing, worker switching and rollback are covered by automated and isolated acceptance checks. Read [official package behavior and validation limits](docs/official-package-status.md).

Install the current Preview 14 client to use this architecture. Source updates do not alter an already installed older client.
