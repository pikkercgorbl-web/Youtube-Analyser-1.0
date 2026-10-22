# Monitoring worker (snapshots / checkpoints).
param([switch]$DryRun)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_radar_start_common.ps1"
$ProjectRoot = Get-RadarProjectRoot
$PythonExe = Get-RadarPythonInterpreter
$workerArgs = @(
    "scripts/run_monitoring_worker.py",
    "--interval-seconds", "900",
    "--error-backoff-seconds", "300"
)
$cmdDisplay = "python " + ($workerArgs -join " ")

if ($DryRun) {
    Write-RadarDryRunPlan -Title "Monitoring worker" -ProjectRoot $ProjectRoot -PythonExe $PythonExe `
        -CommandParts @($cmdDisplay) -WorkerScriptLeaf "run_monitoring_worker.py"
    exit 0
}

Write-Host "=== Radar: Monitoring worker ===" -ForegroundColor Cyan
Initialize-RadarLaunchSession -ProjectRoot $ProjectRoot
Assert-WorkerNotAlreadyRunning -WorkerScriptLeaf "run_monitoring_worker.py"
Assert-LocalRadarDatabaseConnection
Write-Host $cmdDisplay -ForegroundColor Green
Write-Host "Stop: Ctrl+C" -ForegroundColor Gray
python @workerArgs
