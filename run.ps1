# One command: set up everything, then start the API, the live feed, and the dashboard.
param(
    [int]$Port = 8000,
    [switch]$NoFeed,
    [switch]$Dev,
    [switch]$Fresh,
    [int]$ReplayDays = 1100
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvDir = Join-Path $backend ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"
$api = "http://127.0.0.1:$Port"

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }

# --- Fresh start: stop stray feeds/servers and clear the live store ---
if ($Fresh) {
    Info "Fresh start: stopping stray python processes and clearing the live store"
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match "app\.cli" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    Remove-Item (Join-Path $backend "data\live\readings.db") -ErrorAction SilentlyContinue
}

function Resolve-Python {
    foreach ($c in @("py -3", "python", "python3")) {
        if (Get-Command $c.Split(" ")[0] -ErrorAction SilentlyContinue) { return $c }
    }
    throw "Python not found on PATH. Install Python 3.10+ and reopen the terminal."
}

# --- Backend setup ---
Info "Backend setup"
if (-not (Test-Path $venvPy)) {
    $py = Resolve-Python
    Info "Creating virtual environment with '$py'"
    Invoke-Expression "$py -m venv `"$venvDir`""
}
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

# --- Frontend setup ---
Info "Frontend setup"
Push-Location $frontend
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm not found. Install Node.js 18+ and reopen the terminal."
}
if (-not (Test-Path "node_modules")) {
    Info "Installing frontend dependencies (first run)"
    npm install
}
"VITE_API_URL=$api" | Out-File -Encoding ascii ".env"
if (-not $Dev) {
    Info "Building dashboard"
    npm run build
}
Pop-Location

# --- Launch everything in its own window ---
Info "Starting API window -> $api/docs"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backend'; & '$venvPy' -m app.cli serve --port $Port"

if (-not $NoFeed) {
    Start-Sleep -Seconds 6
    Info "Starting live feed window (all cities)"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backend'; & '$venvPy' -m app.cli live-feed --url $api --cities all --delay 1 --replay-days $ReplayDays --loop"
}

Info "Starting dashboard window -> http://127.0.0.1:5173"
if ($Dev) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$frontend'; npm run dev -- --port 5173 --strictPort"
} else {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$frontend'; npm run preview -- --port 5173 --strictPort"
}

Start-Sleep -Seconds 8
Start-Process "http://127.0.0.1:5173"

Info "All running. Dashboard: http://127.0.0.1:5173   API: $api/docs"
Info "Close the API / Feed / Dashboard windows to stop them."
