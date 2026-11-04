$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" -m media_downloader @args
exit $LASTEXITCODE
