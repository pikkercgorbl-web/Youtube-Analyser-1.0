# Outcome capture worker (delayed keyword outcomes).
param([switch]$DryRun)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_radar_start_common.ps1"
$ProjectRoot = Get-RadarProjectRoot
$PythonExe = Get-RadarPythonInterpreter
$workerArgs = @(
    "scripts/run_outcome_capture_worker.py",
    "--interval-seconds", "3600"
)
$cmdDisplay = "python " + ($workerArgs -join " ")

if ($DryRun) {
    Write-RadarDryRunPlan -Title "Outcome worker" -ProjectRoot $ProjectRoot -PythonExe $PythonExe `
        -CommandParts @($cmdDisplay) -WorkerScriptLeaf "run_outcome_capture_worker.py"
    exit 0
}

Write-Host "=== Radar: Outcome worker ===" -ForegroundColor Cyan
Initialize-RadarLaunchSession -ProjectRoot $ProjectRoot
Assert-WorkerNotAlreadyRunning -WorkerScriptLeaf "run_outcome_capture_worker.py"
Assert-LocalRadarDatabaseConnection
Write-Host $cmdDisplay -ForegroundColor Green
Write-Host "Stop: Ctrl+C" -ForegroundColor Gray
python @workerArgs
