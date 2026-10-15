# Outcome capture worker (delayed keyword outcomes).

param(

    [switch]$DryRun,

    [int]$MaxVideos = 0,

    [int]$IntervalSeconds = 3600

)



$ErrorActionPreference = "Stop"

. "$PSScriptRoot\_radar_start_common.ps1"

$ProjectRoot = Get-RadarProjectRoot

$PythonExe = Get-RadarPythonInterpreter

$workerArgs = @(

    "scripts/run_outcome_capture_worker.py",

    "--interval-seconds", "$IntervalSeconds"

)

if ($MaxVideos -gt 0) {

    $workerArgs += @("--max-videos", "$MaxVideos")

}

$cmdDisplay = "python " + ($workerArgs -join " ")



if ($DryRun) {

    Write-RadarDryRunPlan -Title "Outcome worker" -ProjectRoot $ProjectRoot -PythonExe $PythonExe `

        -CommandParts @($cmdDisplay) -WorkerScriptLeaf "run_outcome_capture_worker.py"

    exit 0

}



Write-Host "=== Radar: Outcome worker ===" -ForegroundColor Cyan

Initialize-RadarLaunchSession -ProjectRoot $ProjectRoot

# OUTCOME_CAPTURE_DI_WINNER_PRIORITY: read from ProjectRoot/.env via Python Settings (shell env overrides).

Assert-WorkerNotAlreadyRunning -WorkerScriptLeaf "run_outcome_capture_worker.py"

Assert-LocalRadarDatabaseConnection



$maxVideosArg = if ($MaxVideos -gt 0) { "$MaxVideos" } else { "default" }

python -c @"

import sys

from pathlib import Path

ROOT = Path(r'$ProjectRoot')

sys.path.insert(0, str(ROOT))

from migrate import load_dotenv

load_dotenv(ROOT / '.env')

from app.services.delayed_outcome_capture_config import outcome_capture_budget_for_cycle

mv = int('$maxVideosArg') if '$maxVideosArg' != 'default' else None

b = outcome_capture_budget_for_cycle(max_videos_per_cycle=mv)

print(f'[Outcome worker config] max_videos={b.max_videos_per_cycle} batch_size={b.batch_size} interval_seconds=$IntervalSeconds di_winner_priority={b.di_winner_priority_enabled}')

"@



Write-Host $cmdDisplay -ForegroundColor Green

Write-Host "Stop: Ctrl+C" -ForegroundColor Gray

python @workerArgs

