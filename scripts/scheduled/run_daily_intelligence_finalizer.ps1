# Scheduled wrapper: lock prior UTC daily intelligence reports.
param(
    [string]$ProjectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)
$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$logDir = Join-Path $ProjectRoot "logs\scheduled"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logDir "daily_intelligence_finalizer_$stamp.log"
$python = (Get-Command python).Source
$proc = Start-Process -FilePath $python -ArgumentList "scripts/finalize_daily_intelligence_reports.py" -WorkingDirectory $ProjectRoot -Wait -PassThru -RedirectStandardOutput $logFile -RedirectStandardError $logFile -NoNewWindow
Add-Content -Path $logFile -Value "`nexit_code=$($proc.ExitCode)"
exit $proc.ExitCode
