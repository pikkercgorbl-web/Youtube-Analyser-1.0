# Next.js frontend (port 3000). UTF-8 with BOM for Windows PowerShell 5.1.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Frontend = Join-Path $Root "frontend"
Set-Location -LiteralPath $Frontend

Write-Host "=== YouTube Analytics: Frontend ===" -ForegroundColor Cyan

$nodeCandidates = @()
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    $nodeCandidates += $nodeCmd.Source
}
$nodeCandidates += @(
    "C:\Program Files\nodejs\node.exe"
    "$env:LOCALAPPDATA\Programs\node\node.exe"
)
$nodePaths = @($nodeCandidates | Where-Object { $_ -and (Test-Path $_) })

if (-not $nodePaths -or $nodePaths.Count -eq 0) {
    Write-Host ""
    Write-Host "ERROR: Node.js is not installed." -ForegroundColor Red
    Write-Host "Install LTS from https://nodejs.org/ (Add to PATH), restart terminal." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

$npmCmd = Join-Path (Split-Path $nodePaths[0]) "npm.cmd"
if (-not (Test-Path $npmCmd)) {
    $npmCmd = "npm"
}

if (-not (Test-Path ".env.local")) {
    Copy-Item ".env.local.example" ".env.local"
    Write-Host "Created frontend/.env.local" -ForegroundColor Yellow
}

if (-not (Test-Path "node_modules")) {
    Write-Host "Running npm install (first time may take 1-2 min)..." -ForegroundColor Gray
    & $npmCmd install
}

Write-Host "Site: http://localhost:3000" -ForegroundColor Green
Write-Host "Start backend first: scripts\start-backend.ps1" -ForegroundColor Gray
& $npmCmd run dev
