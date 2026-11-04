$ErrorActionPreference = 'Stop'
$clientPath = Join-Path $PSScriptRoot 'dist\m3\MediaDownloader\MediaDownloader.exe'
$enginePath = Join-Path $PSScriptRoot 'dist\m3\media-engine'
if (-not (Test-Path -LiteralPath $clientPath)) {
    throw 'M3 build is missing. Run scripts/build_m0.py --milestone m3 first.'
}
& $clientPath --engine-dir $enginePath
exit $LASTEXITCODE
