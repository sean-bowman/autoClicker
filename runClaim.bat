@echo off
REM ---------------------------------------------------------------------------
REM Wrapper invoked by the Windows Scheduled Task each hour.
REM
REM Task Scheduler launches with an arbitrary working directory, so we cd into
REM this script's own folder (%~dp0) before running claim.py. Adjust PYTHON below
REM if your interpreter lives elsewhere.
REM ---------------------------------------------------------------------------

set "PYTHON=C:\Users\seanb\miniconda3\python.exe"

cd /d "%~dp0"
"%PYTHON%" claim.py
exit /b %ERRORLEVEL%
