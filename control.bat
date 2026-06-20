@echo off
REM Double-click to open the Boxed Watcher on/off control panel (no console window).
REM Adjust PYTHONW if your interpreter lives elsewhere.
set "PYTHONW=C:\Users\seanb\miniconda3\pythonw.exe"
cd /d "%~dp0"
start "" "%PYTHONW%" "%~dp0control.py"
