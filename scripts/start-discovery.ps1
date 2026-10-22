# Discovery worker (+ enrichment when RADAR_ENRICHMENT_AFTER_DISCOVERY=1 in .env).
param([switch]$DryRun)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_radar_start_common.ps1"
$ProjectRoot = Get-RadarProjectRoot
$PythonExe = Get-RadarPythonInterpreter
$workerArgs = @(
    "scripts/run_discovery_worker.py",
    "--interval-seconds", "300",
    "--error-backoff-seconds", "300",
    "--batch-size", "5"
)
$cmdDisplay = "python " + ($workerArgs -join " ")

if ($DryRun) {
    Write-RadarDryRunPlan -Title "Discovery worker" -ProjectRoot $ProjectRoot -PythonExe $PythonExe `
        -CommandParts @($cmdDisplay) -WorkerScriptLeaf "run_discovery_worker.py"
    exit 0
}

Write-Host "=== Radar: Discovery worker ===" -ForegroundColor Cyan
Initialize-RadarLaunchSession -ProjectRoot $ProjectRoot
Assert-WorkerNotAlreadyRunning -WorkerScriptLeaf "run_discovery_worker.py"
Assert-LocalRadarDatabaseConnection
Write-Host $cmdDisplay -ForegroundColor Green
Write-Host "Stop: Ctrl+C" -ForegroundColor Gray
python @workerArgs
