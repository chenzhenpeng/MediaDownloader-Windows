# Official ParseHub packages

Preview 14 uses the original PyPI ParseHub wheel in a separate embedded execution environment. Package source is not patched or rebuilt by this project. The visible ParseHub version is the upstream version, initially 2.4.0.

This baseline uses `%LOCALAPPDATA%/MediaDownloader/v5`. Earlier engine selections, tasks, settings and credentials are not imported; their files are left untouched. Configure settings and Cookies again after installing.

## Independent update path

Settings → ParseHub → Check official updates reads `https://pypi.org/pypi/parsehub/json`. Stable universal wheels are downloaded only from `files.pythonhosted.org`, using the SHA256 and exact size declared by PyPI HTTPS metadata. This is upstream transport trust, **not** a project signature or a claim of PyPI publisher attestation.

The client retains the original wheel, validates its complete archive and dependency metadata, extracts its bytes without running pip or setup scripts, then runs an isolated compatibility probe. It waits for current tasks to finish before switching workers. A pending switch is confirmed only after the worker handshake; failed or interrupted activation returns to the previous version. Every selected wheel and extracted source file is rechecked on application startup. Normal update checks never install an older or equal version.

The default daily preference checks for new versions; installation still uses the explicit Install button. Version locking prevents installation. Cancellation leaves the active component unchanged.

## Execution environment

Python, worker code and dependencies remain independently signed runtime releases on GitHub. The initial baseline uses Python 3.13.17 and `packaging/official-runtime.lock`. Except for the hash-pinned SignerPy source-only distribution, runtime dependencies are installed from binary wheels during the isolated build job. No dependency resolution or build runs on the user's computer when updating ParseHub.

If upstream Python requirements, dependency versions or extras no longer match the selected environment, installation stops and requests an execution-environment update. It does not silently upgrade dependencies or replace the application. The environment contains OpenCV/NumPy because the unmodified upstream package requires them; a small ParseHub update does not redownload those dependencies.

`.github/workflows/engine-release.yml` builds and signs execution environments on GitHub Actions; local construction is optional. `.github/workflows/upstream-watch.yml` monitors PyPI without modifying a fork, replaying patches or republishing parser code. The former parser-repackaging release workflow has been removed.

## Validation limits

Live acceptance covers public Douyin and Kuaishou video tasks and a Xiaohongshu album with paired Live Photos. Weixin Channels correctly requires local Yuanbao credentials; authenticated Channels download is not established by those tests. Other upstream platforms are discoverable through the adapter but are not all covered by live acceptance. A future upstream API change can still fail the compatibility probe and require an adapter/runtime update.

Local task databases, samples, credentials and signing private keys are not published.
