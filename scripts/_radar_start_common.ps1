# Shared helpers for scripts/start-*.ps1 (visible-terminal Radar launch).
# Dot-source from scripts/; $PSScriptRoot must be the scripts/ directory.

$script:ExpectedDbHost = @("127.0.0.1", "localhost")
$script:ExpectedDbPort = 5433
$script:ExpectedDbName = "youtube_radar_restore_check"

function Get-RadarProjectRoot {
    Split-Path -Parent $PSScriptRoot
}

function Initialize-RadarLaunchSession {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)
    Set-Location -LiteralPath $ProjectRoot
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    # Workers inherit .env DEBUG=true; suppress SQL parameter echo (cycle logs stay on).
    $env:DEBUG = "false"
    $env:RADAR_SQL_ECHO = "false"
}

function Get-RadarPythonInterpreter {
    $cmd = Get-Command python -ErrorAction Stop
    return $cmd.Source
}

function Assert-LocalRadarDatabaseConnection {
    $json = python scripts/stage3_operations_preflight.py
    if ($LASTEXITCODE -ne 0) {
        throw "stage3_operations_preflight.py failed (exit $LASTEXITCODE)"
    }
    $report = $json | ConvertFrom-Json
    $db = $report.database
    $okHost = $db.host -in $script:ExpectedDbHost
    if (-not $okHost -or [int]$db.port -ne $script:ExpectedDbPort -or $db.name -ne $script:ExpectedDbName) {
        throw (
            "Refusing: DATABASE_URL from .env must be " +
            "127.0.0.1:$($script:ExpectedDbPort)/$($script:ExpectedDbName); " +
            "got host=$($db.host) port=$($db.port) name=$($db.name)"
        )
    }
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')] DB OK: $($db.host):$($db.port)/$($db.name)" -ForegroundColor Green
}

function Get-RunningRadarPythonWorker {
    param([Parameter(Mandatory = $true)][string]$WorkerScriptLeaf)
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -like "*$WorkerScriptLeaf*") }
}

function Assert-WorkerNotAlreadyRunning {
    param([Parameter(Mandatory = $true)][string]$WorkerScriptLeaf)
    $running = @(Get-RunningRadarPythonWorker -WorkerScriptLeaf $WorkerScriptLeaf)
    if ($running.Count -gt 0) {
        $pids = ($running | ForEach-Object { $_.ProcessId }) -join ", "
        Write-Host "Worker already running for $WorkerScriptLeaf (PID $pids)." -ForegroundColor Yellow
        Write-Host "Not starting a second instance; existing DB locks preserved." -ForegroundColor Yellow
        exit 1
    }
}

function Write-RadarDryRunPlan {
    param(
        [string]$Title,
        [string]$ProjectRoot,
        [string]$PythonExe,
        [string[]]$CommandParts,
        [int]$LoopIntervalSeconds = 0,
        [string]$WorkerScriptLeaf = ""
    )
    Write-Host "=== DRY RUN: $Title ===" -ForegroundColor Cyan
    Write-Host "ProjectRoot (LiteralPath): $ProjectRoot"
    Write-Host "WorkingDirectory: $ProjectRoot"
    Write-Host "Python: $PythonExe"
    Write-Host "Would remove Env:DATABASE_URL in this process only"
    Write-Host "Would set PYTHONUTF8=1, PYTHONIOENCODING=utf-8"
    Write-Host "Would verify DB: python scripts/stage3_operations_preflight.py (read-only, no secrets printed)"
    if ($WorkerScriptLeaf) {
        Write-Host "Would check no existing process matching: *$WorkerScriptLeaf*"
    }
    if ($LoopIntervalSeconds -gt 0) {
        Write-Host "Loop interval seconds: $LoopIntervalSeconds (sleep after each run; Ctrl+C stops)"
    }
    $cmdLine = ($CommandParts -join " ")
    Write-Host "Command: $cmdLine"
    Write-Host "(No application start, API, or DB writes in DryRun.)" -ForegroundColor Gray
}
