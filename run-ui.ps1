$ErrorActionPreference = 'Stop'
$clientPath = Join-Path $PSScriptRoot 'dist\ui\MediaDownloader\MediaDownloader.exe'
$enginePath = Join-Path $PSScriptRoot 'dist\ui\media-engine'
if (-not (Test-Path -LiteralPath $clientPath)) {
    throw 'UI build is missing. Run scripts/build_m0.py --milestone ui first.'
}
& $clientPath --engine-dir $enginePath
exit $LASTEXITCODE
