param([switch]$Online)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sharedVenv = Join-Path $env:USERPROFILE '.venv'
$activation = Join-Path $sharedVenv 'Scripts\Activate.ps1'
if (-not (Test-Path -LiteralPath $activation)) {
    throw 'Khong tim thay moi truong dung chung. Chay scripts\setup.ps1 truoc.'
}
Set-Location -LiteralPath $projectRoot
& $activation
$env:PYTHONUTF8 = '1'
$env:VNSTOCK_DISABLE_AGENT_SETUP = '1'
$env:VNSTOCK_AGENT_TARGETS = 'none'
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff format --check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m scripts.init_db
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Online) {
    python -m scripts.data_source_check
    exit $LASTEXITCODE
}
Write-Host 'Hoan tat kiem thu offline. Them -Online de kiem tra nguon truc tiep.'

