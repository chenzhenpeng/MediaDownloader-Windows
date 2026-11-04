$ErrorActionPreference = 'Stop'
$clientPath = Join-Path $PSScriptRoot 'dist\m1\MediaDownloader\MediaDownloader.exe'
$enginePath = Join-Path $PSScriptRoot 'dist\m1\media-engine'
if (-not (Test-Path -LiteralPath $clientPath)) {
    throw 'M1 build is missing. Run scripts/build_m0.py --milestone m1 first.'
}
& $clientPath --engine-dir $enginePath
exit $LASTEXITCODE
