# Stop local Postgres container (volume kept)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
docker compose --env-file .env.docker stop db
Write-Host "Stopped db service (volume postgres_data unchanged)." -ForegroundColor Green
