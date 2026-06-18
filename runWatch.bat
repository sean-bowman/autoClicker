@echo off
REM ---------------------------------------------------------------------------
REM Wrapper invoked by the Windows Scheduled Task at logon. Starts the gem-drop
REM watcher, which runs continuously. Task Scheduler launches with an arbitrary
REM working directory, so we cd into this script's own folder (%~dp0) first.
REM Adjust PYTHON below if your interpreter lives elsewhere.
REM ---------------------------------------------------------------------------

set "PYTHON=C:\Users\seanb\miniconda3\python.exe"

cd /d "%~dp0"
"%PYTHON%" watch.py
exit /b %ERRORLEVEL%
