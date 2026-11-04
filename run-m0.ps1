$ErrorActionPreference = 'Stop'
$clientPath = Join-Path $PSScriptRoot 'dist\m0\MediaDownloader\MediaDownloader.exe'
$enginePath = Join-Path $PSScriptRoot 'dist\m0\media-engine'
if (-not (Test-Path -LiteralPath $clientPath)) {
    throw 'M0 build is missing. Run scripts/build_m0.py first.'
}
& $clientPath --engine-dir $enginePath
exit $LASTEXITCODE
