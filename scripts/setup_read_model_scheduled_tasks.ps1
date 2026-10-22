# Idempotent Windows Task Scheduler setup for read-model refresh (Stage 3).
# Install creates DISABLED tasks — enable manually after validation.
param(
    [ValidateSet("DryRun", "Install", "Remove", "Enable")]
    [string]$Action = "DryRun",
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = "",
    [int]$AttentionIntervalHours = 1,
    [string]$KeywordPerformanceLocalTime = "03:15"
)

$ErrorActionPreference = "Stop"
if (-not $PythonExe) {
    $PythonExe = (Get-Command python).Source
}

$attentionName = "NicheScope-Radar-AttentionRefresh"
$keywordName = "NicheScope-Radar-KeywordPerformanceRefresh"
$attentionWrapper = Join-Path $ProjectRoot "scripts\scheduled\run_attention_refresh.ps1"
$keywordWrapper = Join-Path $ProjectRoot "scripts\scheduled\run_keyword_performance_refresh.ps1"

function Invoke-Task {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$TaskArgs)
    $line = "schtasks " + ($TaskArgs -join " ")
    Write-Host $line
    if ($Action -ne "DryRun") {
        & schtasks @TaskArgs
    }
}

if ($Action -eq "Remove") {
    Invoke-Task @("/Delete", "/TN", $attentionName, "/F")
    Invoke-Task @("/Delete", "/TN", $keywordName, "/F")
    exit 0
}

if ($Action -eq "Enable") {
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    foreach ($tn in @($attentionName, $keywordName)) {
        try {
            $t = Get-ScheduledTask -TaskName $tn -ErrorAction Stop
            Set-ScheduledTask -TaskName $tn -Settings $settings | Out-Null
            Enable-ScheduledTask -TaskName $tn | Out-Null
            Write-Host "Enabled $tn (IgnoreNew, StartWhenAvailable)"
        } catch {
            Write-Host "Task missing: $tn - run -Action Install first"
        }
    }
    Get-ScheduledTask -TaskName $attentionName,$keywordName -ErrorAction SilentlyContinue |
        Format-Table TaskName, State, @{N='NextRun';E={(Get-ScheduledTaskInfo $_).NextRunTime}} -AutoSize
    exit 0
}

if ($Action -eq "Install") {
    Invoke-Task @("/Delete", "/TN", $attentionName, "/F")
    Invoke-Task @("/Delete", "/TN", $keywordName, "/F")
}

$attentionTr = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$attentionWrapper`" -ProjectRoot `"$ProjectRoot`""
$keywordTr = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$keywordWrapper`" -ProjectRoot `"$ProjectRoot`""

if ($Action -eq "DryRun") {
    Invoke-Task @(
        "/Create", "/TN", $attentionName,
        "/TR", $attentionTr,
        "/SC", "HOURLY", "/MO", "$AttentionIntervalHours",
        "/ST", "00:00", "/F", "/DISABLE", "/RL", "LIMITED"
    )
} elseif ($Action -eq "Install") {
    & schtasks @("/Create", "/TN", $attentionName, "/TR", $attentionTr, "/SC", "HOURLY", "/MO", "$AttentionIntervalHours", "/ST", "00:00", "/F", "/DISABLE", "/RL", "LIMITED")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "schtasks failed for $attentionName (exit $LASTEXITCODE); using Register-ScheduledTask (Cyrillic/long TR workaround)"
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        $nextHour = (Get-Date).Date.AddHours((Get-Date).Hour + 1)
        if ((Get-Date) -ge $nextHour) { $nextHour = $nextHour.AddHours(1) }
        $tr = New-ScheduledTaskTrigger -Once -At $nextHour -RepetitionInterval (New-TimeSpan -Hours $AttentionIntervalHours) -RepetitionDuration (New-TimeSpan -Days 3650)
        $act = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$attentionWrapper`" -ProjectRoot `"$ProjectRoot`""
        Register-ScheduledTask -TaskName $attentionName -Action $act -Trigger $tr -Settings $settings -Force | Out-Null
        Disable-ScheduledTask -TaskName $attentionName | Out-Null
    }
}
Invoke-Task @(
    "/Create", "/TN", $keywordName,
    "/TR", $keywordTr,
    "/SC", "DAILY", "/ST", $KeywordPerformanceLocalTime,
    "/F", "/DISABLE", "/RL", "LIMITED"
)

$logDir = Join-Path $ProjectRoot "logs\scheduled"
$manifest = [ordered]@{
    action                     = $Action
    python_exe                 = $PythonExe
    project_root               = $ProjectRoot
    tasks_created_disabled     = ($Action -eq "Install")
    attention                  = [ordered]@{
        task_name              = $attentionName
        schedule               = "HOURLY every $AttentionIntervalHours hour(s)"
        wrapper_script         = $attentionWrapper
        log_file_pattern       = (Join-Path $logDir "attention_refresh_*.log")
        exit_code_in_log       = $true
    }
    keyword_performance        = [ordered]@{
        task_name              = $keywordName
        schedule               = "DAILY at $KeywordPerformanceLocalTime (local time)"
        wrapper_script         = $keywordWrapper
        log_file_pattern       = (Join-Path $logDir "keyword_performance_refresh_*.log")
        exit_code_in_log       = $true
    }
    scheduler_settings_not_in_schtasks_cli = [ordered]@{
        multiple_instances     = "Set in GUI: Do not start a new instance (IgnoreNew)"
        missed_start           = "Set in GUI: Run task as soon as possible after scheduled start is missed"
    }
    wrapper_exit_code          = "PowerShell wrappers exit with Python exit code (see exit_code= line in log)"
}

Write-Host ""
Write-Host ($manifest | ConvertTo-Json -Depth 5)
if ($Action -eq "DryRun") {
    $artifactDir = Join-Path $ProjectRoot "artifacts"
    New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
    $outPath = Join-Path $artifactDir "stage3_scheduler_dryrun.json"
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $outPath -Encoding utf8
    Write-Host "Wrote $outPath"
}

Write-Host ""
Write-Host "Prepared tasks (DISABLED on Install): $attentionName, $keywordName"
Write-Host "Enable only after: python scripts/stage3_operations_preflight.py"
