# Preview 13 current-client baseline

This release does not maintain older-client update discovery or data migration.

- GitHub Latest identifies the current application installer. Runtime/parser/tool releases remain separate and do not become Latest.
- Component discovery uses only the fixed signed `channel-stable` catalog. The single-release fallback and its scheduled Latest renewal workflow are removed.
- Default application data starts at `%LOCALAPPDATA%/MediaDownloader/v4`. Older settings, credentials and history are not imported; old data and downloaded works are left untouched.
- The task database accepts only a fresh database or schema 4. It does not add missing historical columns, reconstruct historical attempts or repair version-specific legacy metadata.
- Completed files require the platform/post folder layout, a matching commit token and every file's SHA-256. Historical flat directories and permissive manifest validation are removed.
- Current task recovery, process ownership, cancellation, signed update verification and explicit rollback remain required behavior.

Users should uninstall the previous application before installing this release and configure their preferences and credentials again. The installer remains a current-user native x64 EXE. The official-package migration path is still experimental; see [migration status](official-package-status.md).
