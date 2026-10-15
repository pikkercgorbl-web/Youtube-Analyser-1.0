# Daily intelligence finalizer (DISABLED on Install — enable manually). UTC day lock ~06:05 local (UTC+6).
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

$taskName = "NicheScope-Radar-DailyIntelligenceFinalizer"
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$wrapper = Join-Path $ProjectRoot "scripts\scheduled\run_daily_intelligence_finalizer.ps1"

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
        Write-Host "Enabled $taskName"
    } catch {
        Write-Host "Task missing: $taskName - run -Action Install first"
        exit 1
    }
    exit 0
}

if ($Action -eq "Install") {
    Invoke-Task @("/Delete", "/TN", $taskName, "/F")
}

$tr = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$wrapper`" -ProjectRoot `"$ProjectRoot`""
Write-Host "Task: $taskName"
Write-Host "Wrapper: $wrapper"
Write-Host "Schedule: daily $LocalRunTime (local clock — use UTC+6 host after midnight UTC)"
Write-Host "CLI: python scripts/finalize_daily_intelligence_reports.py"

if ($Action -eq "DryRun") {
    exit 0
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$wrapper`" -ProjectRoot `"$ProjectRoot`""
$trigger = New-ScheduledTaskTrigger -Daily -At $LocalRunTime
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Description "Lock prior UTC daily intelligence reports" | Out-Null
Disable-ScheduledTask -TaskName $taskName | Out-Null
Write-Host "Installed DISABLED: $taskName"
