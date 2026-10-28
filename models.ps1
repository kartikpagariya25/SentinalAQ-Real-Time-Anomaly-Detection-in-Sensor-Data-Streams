# View all trained models and their metrics.
#   .\models.ps1          metrics table + selected model
#   .\models.ps1 -Info    also prints a short description of every model
param(
    [switch]$Info
)

$ErrorActionPreference = "Stop"
$backend = Join-Path $PSScriptRoot "backend"
$venvPy = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPy)) {
    Write-Host "Virtual env not found. Run .\backend.ps1 first." -ForegroundColor Yellow
    exit 1
}

Push-Location $backend
if ($Info) {
    & $venvPy -m app.cli models --info
} else {
    & $venvPy -m app.cli models
}
Pop-Location

Write-Host ""
Read-Host "Press Enter to close"
