@echo off
cd /d "%~dp0"
echo Running FlowType with a visible console - errors will show here. Close this window to stop.
".venv\Scripts\python.exe" flowtype.py
pause
