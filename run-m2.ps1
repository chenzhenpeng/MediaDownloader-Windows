$ErrorActionPreference = 'Stop'
$clientPath = Join-Path $PSScriptRoot 'dist\m2\MediaDownloader\MediaDownloader.exe'
$enginePath = Join-Path $PSScriptRoot 'dist\m2\media-engine'
if (-not (Test-Path -LiteralPath $clientPath)) {
    throw 'M2 build is missing. Run scripts/build_m0.py --milestone m2 first.'
}
& $clientPath --engine-dir $enginePath
exit $LASTEXITCODE
