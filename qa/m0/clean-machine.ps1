param(
    [string]$ApplicationRoot = (Join-Path $PSScriptRoot 'MediaDownloader'),
    [string]$ResultsRoot = (Join-Path $PSScriptRoot ('M0-results-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
)
$ErrorActionPreference = 'Stop'
$clientPath = Join-Path $ApplicationRoot 'MediaDownloader.exe'
$enginePath = Join-Path $ApplicationRoot 'engine\media-engine.exe'
if (-not (Test-Path -LiteralPath $clientPath) -or -not (Test-Path -LiteralPath $enginePath)) {
    throw 'Extract the M0 archive before running this script.'
}
New-Item -ItemType Directory -Path $ResultsRoot | Out-Null
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$report = [ordered]@{
    windows = [Environment]::OSVersion.VersionString
    administrator = $isAdministrator
    pythonOnPath = [bool](Get-Command python.exe -ErrorAction SilentlyContinue)
    ffmpegOnPath = [bool](Get-Command ffmpeg.exe -ErrorAction SilentlyContinue)
    scope = 'Actual environment must be independently verified as a clean Windows VM/machine'
}
$env:MEDIA_DOWNLOADER_DATA_DIR = Join-Path $ResultsRoot 'app-data'
& $enginePath --self-test --output (Join-Path $ResultsRoot 'engine-self-test') |
    Out-File -LiteralPath (Join-Path $ResultsRoot 'engine-output.json') -Encoding utf8
$report.engineExitCode = $LASTEXITCODE
& $clientPath --smoke-test (Join-Path $ResultsRoot 'window.png')
$report.uiExitCode = $LASTEXITCODE
$report.passed = ($report.engineExitCode -eq 0 -and $report.uiExitCode -eq 0 -and -not $isAdministrator -and
    -not $report.pythonOnPath -and -not $report.ffmpegOnPath)
$report | ConvertTo-Json | Out-File -LiteralPath (Join-Path $ResultsRoot 'environment.json') -Encoding utf8
if (-not $report.passed) {
    throw 'M0 acceptance incomplete: inspect results and run under a standard user on a verified clean machine.'
}
Write-Output ('Results: ' + $ResultsRoot)
