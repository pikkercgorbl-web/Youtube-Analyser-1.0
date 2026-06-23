# Запуск FastAPI-бэкенда (порт 8000)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "=== YouTube Analytics: Backend ===" -ForegroundColor Cyan

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Создан файл .env из .env.example" -ForegroundColor Yellow
    Write-Host "Добавьте YOUTUBE_API_KEYS в .env для поиска через YouTube API." -ForegroundColor Yellow
}

Write-Host "Проверка зависимостей Python..." -ForegroundColor Gray
python -m pip install -q -r requirements.txt

New-Item -ItemType Directory -Force -Path "data" | Out-Null

Write-Host "Запуск сервера: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Документация API: http://127.0.0.1:8000/docs" -ForegroundColor Green
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
