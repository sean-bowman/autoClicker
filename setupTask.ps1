<#
.SYNOPSIS
    Register (or refresh) the hourly Windows Scheduled Task that claims boxed.gg
    gem drops.

.DESCRIPTION
    Creates a task named "BoxedGemClaimer" that runs runClaim.bat once per hour.
    The task is registered for the current user and runs whether or not that user
    is logged in. Re-running this script is safe: it removes any existing task of
    the same name first, so it doubles as an updater.

.NOTES
    Run from an elevated PowerShell prompt the first time (registering a task that
    runs while logged off requires it). Stored credentials are handled by the OS,
    not by this repo.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setupTask.ps1
#>

$ErrorActionPreference = 'Stop'

$taskName = 'BoxedGemClaimer'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$batPath = Join-Path $scriptDir 'runClaim.bat'

if (-not (Test-Path $batPath)) {
    throw "runClaim.bat not found at $batPath"
}

# Remove any prior registration so this script is idempotent.
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$taskName'..."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# Action: run the .bat wrapper from the repo directory.
$action = New-ScheduledTaskAction -Execute $batPath -WorkingDirectory $scriptDir

# Trigger: start now, then repeat every hour indefinitely. The drop pool
# replenishes hourly, matching CLAIM_INTERVAL_HOURS in config.py.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 1)

# Settings: allow on-battery operation and start late if a run was missed
# (e.g. the machine was asleep at the top of the hour).
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $taskName `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Claims the hourly boxed.gg gem-drop pool.' | Out-Null

Write-Host "Registered scheduled task '$taskName' (hourly)."
Write-Host "Trigger a test run now with:  schtasks /run /tn $taskName"
