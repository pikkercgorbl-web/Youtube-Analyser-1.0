# Start local Postgres (Docker) — data volume preserved
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path ".env.docker")) {
    Write-Host "Create .env.docker from .env.docker.example" -ForegroundColor Red
    exit 1
}

Write-Host "=== Radar: Docker PostgreSQL (127.0.0.1:5433) ===" -ForegroundColor Cyan
docker compose --env-file .env.docker up -d db
docker compose --env-file .env.docker ps
