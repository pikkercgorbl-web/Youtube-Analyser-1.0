# Запуск Next.js-фронтенда (порт 3000)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Frontend = Join-Path $Root "frontend"
Set-Location $Frontend

Write-Host "=== YouTube Analytics: Frontend ===" -ForegroundColor Cyan

$nodePaths = @(
    (Get-Command node -ErrorAction SilentlyContinue)?.Source,
    "C:\Program Files\nodejs\node.exe",
    "$env:LOCALAPPDATA\Programs\node\node.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $nodePaths) {
    Write-Host ""
    Write-Host "ОШИБКА: Node.js не установлен." -ForegroundColor Red
    Write-Host ""
    Write-Host "1. Скачайте LTS-версию: https://nodejs.org/" -ForegroundColor Yellow
    Write-Host "2. Установите с галочкой 'Add to PATH'" -ForegroundColor Yellow
    Write-Host "3. Перезапустите терминал и снова выполните этот скрипт." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

$npmCmd = Join-Path (Split-Path $nodePaths[0]) "npm.cmd"
if (-not (Test-Path $npmCmd)) {
    $npmCmd = "npm"
}

if (-not (Test-Path ".env.local")) {
    Copy-Item ".env.local.example" ".env.local"
    Write-Host "Создан frontend/.env.local" -ForegroundColor Yellow
}

if (-not (Test-Path "node_modules")) {
    Write-Host "Установка npm-зависимостей (первый раз может занять 1–2 мин)..." -ForegroundColor Gray
    & $npmCmd install
}

Write-Host "Запуск сайта: http://localhost:3000" -ForegroundColor Green
Write-Host "Убедитесь, что бэкенд запущен: scripts\start-backend.ps1" -ForegroundColor Gray
& $npmCmd run dev
