$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sharedVenv = Join-Path $env:USERPROFILE '.venv'
$venvPython = Join-Path $sharedVenv 'Scripts\python.exe'
$pythonExecutable = $null

# Prefer the existing shared environment; no dependence on a broken py registry.
if (Test-Path -LiteralPath $venvPython) {
    $pythonExecutable = $venvPython
} else {
    $localPrograms = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $localPrograms) {
        $pythonCandidates = Get-ChildItem -LiteralPath $localPrograms -Directory |
            Sort-Object Name -Descending
        foreach ($candidate in $pythonCandidates) {
            $candidateExe = Join-Path $candidate.FullName 'python.exe'
            if (Test-Path -LiteralPath $candidateExe) {
                & $candidateExe -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
                if ($LASTEXITCODE -eq 0) {
                    $pythonExecutable = $candidateExe
                    break
                }
            }
        }
    }
    if (-not $pythonExecutable) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCommand -and $pythonCommand.Source -notlike '*\WindowsApps\*') {
            $pythonExecutable = $pythonCommand.Source
        }
    }
}
if (-not $pythonExecutable) {
    throw 'Can cai Python >= 3.11 tu https://www.python.org/downloads/windows/ va chon Add Python to PATH. Script khong tu cai Python.'
}
& $pythonExecutable -c "import sys; print(sys.version); sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'Du an yeu cau Python >= 3.11.' }
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $pythonExecutable -m venv $sharedVenv
    if ($LASTEXITCODE -ne 0) { throw 'Khong tao duoc moi truong dung chung ~/.venv.' }
}
& (Join-Path $sharedVenv 'Scripts\Activate.ps1')
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'
$env:VNSTOCK_DISABLE_AGENT_SETUP = '1'
$env:VNSTOCK_AGENT_TARGETS = 'none'
python -m pip install -U pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pip install -U --extra-index-url https://vnstocks.com/api/simple 'vnstock>=4.0.9' 'vnai>=2.6.2'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pip install -e '.[dev]'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) {
    Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination (Join-Path $projectRoot '.env')
}
& (Join-Path $PSScriptRoot 'run_checks.ps1')
exit $LASTEXITCODE

