param(
    [ValidateSet('components', 'app', 'installer')][string]$Stage = 'installer',
    [string]$Components,
    [string]$WorkDir,
    [string]$SevenZip,
    [switch]$QA
)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv before building.' }
    uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'Dependency synchronization failed.' }
    $buildArgs = @('--stage', $Stage)
    if ($Components) { $buildArgs += @('--components', $Components) }
    if ($WorkDir) { $buildArgs += @('--work-dir', $WorkDir) }
    if ($SevenZip) { $buildArgs += @('--sevenzip', $SevenZip) }
    if ($QA) { $buildArgs += '--qa' }
    uv run --no-sync python scripts/build_windows.py @buildArgs
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
}
finally { Pop-Location }
