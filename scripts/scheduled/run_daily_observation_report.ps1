# Scheduled wrapper: UTC daily observation originals + 14d index (read-only DB).
param(
    [string]$ProjectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [int]$MaxDays = 14
)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $ProjectRoot
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:DEBUG = "false"
$env:RADAR_SQL_ECHO = "false"

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$logDir = Join-Path $ProjectRoot "logs\scheduled"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logDir "daily_observation_$stamp.log"
$python = (Get-Command python).Source
$header = @(
    "daily_observation_wrapper_start=$stamp",
    "project_root=$ProjectRoot",
    "python_exe=$python",
    "working_directory=$ProjectRoot",
    "database_url_source=.env (shell DATABASE_URL cleared before python)"
)
Set-Content -Path $logFile -Value ($header -join "`n") -Encoding utf8
$argsList = @(
    "scripts/radar_daily_observation_report.py",
    "--catch-up",
    "--max-days", "$MaxDays"
)
# PowerShell 5.1: Start-Process cannot redirect stdout+stderr to the same file.
Push-Location -LiteralPath $ProjectRoot
try {
    & $python @argsList 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) { $exitCode = 0 }
} finally {
    Pop-Location
}
Add-Content -Path $logFile -Value "`nexit_code=$exitCode" -Encoding utf8
exit $exitCode
