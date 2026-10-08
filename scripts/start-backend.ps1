# FastAPI backend (port 8000). Save as UTF-8 with BOM for Windows PowerShell 5.1.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

Write-Host "=== YouTube Analytics: Backend ===" -ForegroundColor Cyan
if ($env:DATABASE_URL) {
    Write-Host "Note: `$env:DATABASE_URL in this shell overrides .env - use Remove-Item Env:DATABASE_URL" -ForegroundColor Yellow
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example" -ForegroundColor Yellow
    Write-Host "Add YOUTUBE_API_KEYS to .env for YouTube Data API search." -ForegroundColor Yellow
}

Write-Host "Checking Python dependencies..." -ForegroundColor Gray
python -m pip install -q -r requirements.txt

New-Item -ItemType Directory -Force -Path "data" | Out-Null

Write-Host "Server: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "API docs: http://127.0.0.1:8000/docs" -ForegroundColor Green
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
