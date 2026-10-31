# Set up and run the entire backend: API + a continuous demo feed.
param(
    [int]$Port = 8000,
    [switch]$NoFeed,
    [switch]$SetupOnly,
    [int]$ReplayDays = 1100
)

$ErrorActionPreference = "Stop"
$backend = Join-Path $PSScriptRoot "backend"
$venvDir = Join-Path $backend ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }

function Resolve-Python {
    foreach ($c in @("py -3", "python", "python3")) {
        if (Get-Command $c.Split(" ")[0] -ErrorAction SilentlyContinue) { return $c }
    }
    throw "Python not found on PATH. Install Python 3.10+ and reopen the terminal."
}

if (-not (Test-Path $venvPy)) {
    $py = Resolve-Python
    Info "Creating virtual environment with '$py'"
    Invoke-Expression "$py -m venv `"$venvDir`""
}

Info "Installing dependencies"
& $venvPy -m pip install -r (Join-Path $backend "requirements.txt")

Push-Location $backend
if (-not (Test-Path "data\synthetic\sensor_data.parquet")) {
    Info "First run: generating synthetic data (a few minutes)"
    & $venvPy -m app.cli profile
    & $venvPy -m app.cli generate
}
if (-not (Test-Path "models\detector.joblib")) {
    Info "Training the selected model"
    & $venvPy -m app.cli train
}
Pop-Location

if ($SetupOnly) {
    Info "Backend ready. Run .\backend.ps1 to start the API."
    return
}

Info "Starting API on http://127.0.0.1:$Port  (Swagger at /docs)"
Start-Process -FilePath $venvPy -ArgumentList "-m", "app.cli", "serve", "--port", "$Port" -WorkingDirectory $backend

if (-not $NoFeed) {
    Start-Sleep -Seconds 6
    Info "Starting continuous demo feed (readings pushed over HTTP)"
    Start-Process -FilePath $venvPy -ArgumentList "-m", "app.cli", "live-feed", "--url", "http://127.0.0.1:$Port", "--cities", "all", "--delay", "1", "--replay-days", "$ReplayDays", "--loop" -WorkingDirectory $backend
}

Info "Backend is running. API: http://127.0.0.1:$Port/docs   Dashboard: run .\dashboard.ps1"
