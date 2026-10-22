# Local Postgres via Docker (volume preserved). UTF-8 with BOM for Windows PowerShell 5.1.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

if (-not (Test-Path ".env.docker")) {
    Write-Host "Create .env.docker from .env.docker.example" -ForegroundColor Red
    exit 1
}

Write-Host "=== Radar: Docker PostgreSQL (127.0.0.1:5433) ===" -ForegroundColor Cyan
docker compose --env-file .env.docker up -d db
docker compose --env-file .env.docker ps
