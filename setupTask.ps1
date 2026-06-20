<#
.SYNOPSIS
    Register (and start) the Windows Scheduled Task that runs the boxed.gg
    gem-drop watcher in the background, for as long as you are logged on.

.DESCRIPTION
    Creates a task named "BoxedGemWatcher" that launches watch.py with pythonw.exe
    (so there is no console window) at logon, and keeps it running. The watcher is
    a long-lived process: it keeps boxed.gg open off-screen, polls the chat, and
    claims each drop as it goes live: so the task is configured to:
      * start at logon (a real, off-screen Chrome window needs the interactive
        session, so this can't run while logged off),
      * never time out,
      * restart automatically if the process dies,
      * allow only one instance at a time.

    Re-running this script is safe: it removes any existing task first, re-creates
    it, and starts it immediately. Registering a logon task for your own account
    does not require an elevated prompt.

.PARAMETER Python
    Path to your python.exe. The script derives pythonw.exe (windowless) from it.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setupTask.ps1
#>

param(
    [string]$Python = 'C:\Users\seanb\miniconda3\python.exe'
)

$ErrorActionPreference = 'Stop'

$taskName = 'BoxedGemWatcher'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$watcher = Join-Path $scriptDir 'watch.py'

# Prefer pythonw.exe (no console window) sitting next to python.exe.
$pythonw = $Python -replace 'python\.exe$', 'pythonw.exe'
if (-not (Test-Path $pythonw)) {
    Write-Warning "pythonw.exe not found at $pythonw; falling back to $Python (a console window may appear)."
    $pythonw = $Python
}
if (-not (Test-Path $watcher)) {
    throw "watch.py not found at $watcher"
}

# Remove any prior registration so this script is idempotent.
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Write-Host "Removing existing task '$taskName'..."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# Action: run the watcher windowlessly, from the repo directory.
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$watcher`"" -WorkingDirectory $scriptDir

# Trigger: at this user's logon (the watcher needs the interactive session).
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Settings: run indefinitely, survive battery, restart on failure, single instance.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)   # 0 = no time limit

# Run in the user's own context, only while logged on (interactive session).
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'Continuously watches boxed.gg and claims each gem drop (background).' | Out-Null

# Start it now so you don't have to log out / in first.
Start-ScheduledTask -TaskName $taskName

Write-Host "Registered and started '$taskName'."
Write-Host "It now runs in the background at every logon. Manage it with:"
Write-Host "  Stop:    schtasks /end  /tn $taskName"
Write-Host "  Start:   schtasks /run  /tn $taskName"
Write-Host "  Status:  schtasks /query /tn $taskName /v /fo LIST"
Write-Host "  Remove:  Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"
Write-Host "Watch progress in logs\watch.log"
