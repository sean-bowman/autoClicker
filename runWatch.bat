@echo off
REM ---------------------------------------------------------------------------
REM Convenience launcher for running the watcher MANUALLY in the foreground
REM (a console window stays open showing its log). The background Scheduled Task
REM does NOT use this file: it launches pythonw.exe directly (see setupTask.ps1)
REM so no window appears. Adjust PYTHON below if your interpreter lives elsewhere.
REM ---------------------------------------------------------------------------

set "PYTHON=C:\Users\seanb\miniconda3\python.exe"

cd /d "%~dp0"
"%PYTHON%" watch.py %*
exit /b %ERRORLEVEL%
