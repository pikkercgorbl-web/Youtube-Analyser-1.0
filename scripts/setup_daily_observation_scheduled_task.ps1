# Daily UTC observation report task (DISABLED on Install — enable manually).
# Schedule: 06:05 local time (UTC+6 → after 00:00 UTC).
param(
    [ValidateSet("DryRun", "Install", "Remove", "Enable")]
    [string]$Action = "DryRun",
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = "",
    [string]$LocalRunTime = "06:05"
)

$ErrorActionPreference = "Stop"
if (-not $PythonExe) {
    $PythonExe = (Get-Command python).Source
}

$taskName = "NicheScope-Radar-DailyObservationReport"
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$wrapper = Join-Path $ProjectRoot "scripts\scheduled\run_daily_observation_report.ps1"
$useRegister = $ProjectRoot -match '[^\u0000-\u007F]'

function Invoke-Task {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$TaskArgs)
    $line = "schtasks " + ($TaskArgs -join " ")
    Write-Host $line
    if ($Action -ne "DryRun") {
        & schtasks @TaskArgs
    }
}

if ($Action -eq "Remove") {
    Invoke-Task @("/Delete", "/TN", $taskName, "/F")
    exit 0
}

if ($Action -eq "Enable") {
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    try {
        Set-ScheduledTask -TaskName $taskName -Settings $settings | Out-Null
        Enable-ScheduledTask -TaskName $taskName | Out-Null
        Write-Host "Enabled $taskName (IgnoreNew, StartWhenAvailable)"
    } catch {
        Write-Host "Task missing: $taskName - run -Action Install first"
        exit 1
    }
    Get-ScheduledTask -TaskName $taskName | Format-Table TaskName, State, @{N='NextRun';E={(Get-ScheduledTaskInfo $_).NextRunTime}} -AutoSize
    exit 0
}

if ($Action -eq "Install") {
    if ($useRegister) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    } else {
        Invoke-Task @("/Delete", "/TN", $taskName, "/F")
    }
}

$taskTr = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$wrapper`" -ProjectRoot `"$ProjectRoot`""

function Install-ObservationScheduledTask {
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $psArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$wrapper`" -ProjectRoot `"$ProjectRoot`""
    $act = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $psArgs -WorkingDirectory $ProjectRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At ([DateTime]::ParseExact($LocalRunTime, "HH:mm", $null))
    Register-ScheduledTask -TaskName $taskName -Action $act -Trigger $trigger -Settings $settings -Force | Out-Null
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    Write-Host "Registered via Register-ScheduledTask (WorkingDirectory=$ProjectRoot)"
}

if ($Action -eq "DryRun") {
    if ($useRegister) {
        Write-Host "DryRun: non-ASCII ProjectRoot -> would use Register-ScheduledTask + WorkingDirectory (schtasks /TR breaks on Cyrillic)"
        Write-Host "  Action: powershell.exe -File `"$wrapper`" -ProjectRoot `"$ProjectRoot`""
        Write-Host "  Trigger: DAILY $LocalRunTime local; Settings: IgnoreNew, StartWhenAvailable"
    } else {
        Invoke-Task @(
            "/Create", "/TN", $taskName,
            "/TR", $taskTr,
            "/SC", "DAILY", "/ST", $LocalRunTime,
            "/F", "/DISABLE", "/RL", "LIMITED"
        )
    }
} elseif ($Action -eq "Install") {
    if ($useRegister) {
        Install-ObservationScheduledTask
    } else {
        & schtasks @("/Create", "/TN", $taskName, "/TR", $taskTr, "/SC", "DAILY", "/ST", $LocalRunTime, "/F", "/DISABLE", "/RL", "LIMITED")
        if ($LASTEXITCODE -ne 0) {
            Write-Host "schtasks failed (exit $LASTEXITCODE); using Register-ScheduledTask"
            Install-ObservationScheduledTask
        }
    }
}

$manifest = [ordered]@{
    action                 = $Action
    task_name              = $taskName
    schedule_local         = "DAILY at $LocalRunTime (machine local timezone; UTC+6 ≈ after UTC midnight)"
    wrapper_script         = $wrapper
    cli_equivalent         = "python scripts/radar_daily_observation_report.py --catch-up --max-days 14"
    log_file_pattern       = (Join-Path $ProjectRoot "logs\scheduled\daily_observation_*.log")
    tasks_created_disabled = ($Action -eq "Install")
    enable_command         = ".\scripts\setup_daily_observation_scheduled_task.ps1 -Action Enable"
    manual_run             = ".\scripts\scheduled\run_daily_observation_report.ps1"
}

Write-Host ($manifest | ConvertTo-Json -Depth 4)
if ($Action -eq "DryRun") {
    $outPath = Join-Path $ProjectRoot "artifacts\daily_observation_scheduler_dryrun.json"
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $outPath -Encoding utf8
    Write-Host "Wrote $outPath"
}

Write-Host ""
Write-Host "Task $taskName prepared DISABLED on Install. Enable only after read-only trial."
