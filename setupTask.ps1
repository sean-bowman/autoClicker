<#
.SYNOPSIS
    Register (or refresh) the Windows Scheduled Task that runs the boxed.gg
    gem-drop watcher continuously.

.DESCRIPTION
    Creates a task named "BoxedGemWatcher" that starts runWatch.bat at logon and
    keeps it running. The watcher is a long-lived process (it polls the chat and
    claims each drop as it goes live), so the task is configured to start at logon,
    never time out, and restart automatically if the process dies. Re-running this
    script is safe: it removes any existing task of the same name first.

    The watcher drives a real (off-screen) Chrome window, which needs an
    interactive desktop session — hence the logon trigger rather than a
    run-while-logged-off task.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setupTask.ps1
#>

$ErrorActionPreference = 'Stop'

$taskName = 'BoxedGemWatcher'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$batPath = Join-Path $scriptDir 'runWatch.bat'

if (-not (Test-Path $batPath)) {
    throw "runWatch.bat not found at $batPath"
}

# Remove any prior registration so this script is idempotent.
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$taskName'..."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# Action: run the watcher wrapper from the repo directory.
$action = New-ScheduledTaskAction -Execute $batPath -WorkingDirectory $scriptDir

# Trigger: at user logon (the watcher needs the interactive session for Chrome).
$trigger = New-ScheduledTaskTrigger -AtLogOn

# Settings: run indefinitely, restart on failure, only one instance at a time.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)   # 0 = no time limit

Register-ScheduledTask -TaskName $taskName `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Continuously watches boxed.gg and claims each gem drop.' | Out-Null

Write-Host "Registered scheduled task '$taskName' (starts at logon, keeps running)."
Write-Host "Start it now without logging out:  schtasks /run /tn $taskName"
Write-Host "Stop it:                           schtasks /end /tn $taskName"
