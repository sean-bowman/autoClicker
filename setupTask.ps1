<#
.SYNOPSIS
    Register the Windows Scheduled Task that runs the boxed.gg gem-drop watcher.
    The task is on-demand only: it does NOT auto-launch at logon. Start and stop
    it with the control panel (control.py / control.bat) or schtasks.

.DESCRIPTION
    Creates a task named "BoxedGemWatcher" that launches watch.py with pythonw.exe
    (so there is no console window). The watcher is a long-lived process: it keeps
    boxed.gg open off-screen, polls the chat, and claims each drop as it goes live.
    The task is configured to:
      * run only on demand (no startup trigger; you launch it from the control panel),
      * never time out,
      * restart automatically if the process dies while running,
      * allow only one instance at a time.

    It still needs an interactive session (a real, off-screen Chrome window), so
    only start it while logged on.

    Re-running this script is safe: it removes any existing task first and
    re-creates it. Registering a task for your own account does not require an
    elevated prompt.

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

# No trigger: the task runs on demand only (started via the control panel).
# This is the deliberate change from auto-start-at-logon behaviour.

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

# Register without a trigger -> an on-demand task.
Register-ScheduledTask -TaskName $taskName `
    -Action $action -Settings $settings -Principal $principal `
    -Description 'Watches boxed.gg and claims each gem drop. On-demand only (start/stop via control.py); does not auto-launch at startup.' | Out-Null

Write-Host "Registered '$taskName' as an on-demand task (no auto-start at logon)."
Write-Host "Control it with the panel:"
Write-Host "  GUI:     double-click control.bat  (or  pythonw control.py)"
Write-Host "  Start:   python control.py --on      (or  schtasks /run /tn $taskName)"
Write-Host "  Stop:    python control.py --off     (or  schtasks /end /tn $taskName)"
Write-Host "  Status:  python control.py --status"
Write-Host "  Remove:  Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"
Write-Host "Watch progress in logs\watch.log"
