# Build and serve the dashboard (stable), or run the dev server with -Dev.
param(
    [int]$Port = 5173,
    [string]$ApiUrl = "http://127.0.0.1:8000",
    [switch]$Dev,
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$frontend = Join-Path $PSScriptRoot "frontend"

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "npm not found. Install Node.js 18+ and reopen the terminal." -ForegroundColor Yellow
    exit 1
}

Push-Location $frontend
if (-not (Test-Path "node_modules")) {
    Info "Installing frontend dependencies (first run)"
    npm install
}

# Point the dashboard at the API
"VITE_API_URL=$ApiUrl" | Out-File -Encoding ascii ".env"

if ($Dev) {
    Info "Opening dashboard (dev, hot-reload) at http://127.0.0.1:$Port"
    Start-Process "http://127.0.0.1:$Port"
    npm run dev -- --port $Port
} else {
    if ($Rebuild -or -not (Test-Path "dist")) {
        Info "Building dashboard"
        npm run build
    }
    Info "Serving dashboard at http://127.0.0.1:$Port  (stable mode; use -Dev while editing)"
    Start-Process "http://127.0.0.1:$Port"
    npm run preview -- --port $Port --strictPort
}
Pop-Location
