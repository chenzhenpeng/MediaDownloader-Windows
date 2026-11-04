$ErrorActionPreference = 'Stop'
$clientPath = Join-Path $PSScriptRoot 'dist\m4\MediaDownloader\MediaDownloader.exe'
$enginePath = Join-Path $PSScriptRoot 'dist\m4\media-engine'
if (-not (Test-Path -LiteralPath $clientPath)) {
    throw 'M4 build is missing. Run scripts/build_m0.py --milestone m4 first.'
}
& $clientPath --engine-dir $enginePath
exit $LASTEXITCODE
