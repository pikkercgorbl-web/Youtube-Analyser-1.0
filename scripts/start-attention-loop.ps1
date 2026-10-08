# Attention read model: run immediately, then every IntervalSeconds (default 3600).
param(
    [switch]$DryRun,
    [int]$IntervalSeconds = 3600
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_radar_start_common.ps1"
$ProjectRoot = Get-RadarProjectRoot
$PythonExe = Get-RadarPythonInterpreter
$cmdDisplay = "python scripts/refresh_attention_engine.py"

if ($DryRun) {
    Write-RadarDryRunPlan -Title "Attention refresh loop" -ProjectRoot $ProjectRoot -PythonExe $PythonExe `
        -CommandParts @($cmdDisplay) -LoopIntervalSeconds $IntervalSeconds
    exit 0
}

Write-Host "=== Radar: Attention refresh loop (interval ${IntervalSeconds}s) ===" -ForegroundColor Cyan
Initialize-RadarLaunchSession -ProjectRoot $ProjectRoot
Write-Host "Stop: Ctrl+C. Do not run together with Task Scheduler Attention task." -ForegroundColor Gray

while ($true) {
    $started = Get-Date
    try {
        Assert-LocalRadarDatabaseConnection
        Write-Host "`n[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')] $cmdDisplay"
        python scripts/refresh_attention_engine.py
        $code = $LASTEXITCODE
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')] exit_code=$code"
    } catch {
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')] $($_.Exception.Message)" -ForegroundColor Red
    }
    $elapsed = ((Get-Date) - $started).TotalSeconds
    $sleep = [Math]::Max(0, $IntervalSeconds - $elapsed)
    Write-Host "Sleep ${sleep}s until next run."
    Start-Sleep -Seconds $sleep
}
