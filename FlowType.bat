@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo FlowType is not set up yet. Run setup.bat first.
  pause
  exit /b 1
)
rem stop any running copy so this always (re)starts the latest version
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*flowtype.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
start "" ".venv\Scripts\pythonw.exe" "%~dp0flowtype.py"
