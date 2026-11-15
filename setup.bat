@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title FlowType setup
set "LOG=%~dp0setup.log"
echo FlowType setup %date% %time% > "%LOG%"
echo === FlowType setup ===
echo (Full details are written to setup.log)
echo.

call :findpython
if not defined PYEXE call :install312
if not defined PYEXE (
  echo [X] Could not find or install Python. Install Python 3.12 from python.org, then run setup.bat again.
  goto end
)
echo Using Python: "%PYEXE%"
echo Using Python: "%PYEXE%" >> "%LOG%"

:makevenv
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating environment...
  "%PYEXE%" -m venv .venv >> "%LOG%" 2>&1
)
if not exist ".venv\Scripts\python.exe" (
  echo [X] Could not create the environment. See setup.log
  goto end
)

echo [2/3] Installing packages - this takes 2-5 minutes, please wait...
".venv\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 goto pipfail

echo [3/3] Downloading the speech model (one time, ~500 MB)...
".venv\Scripts\python.exe" flowtype.py --download-model >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [X] Model download failed. Check your internet and run setup.bat again. Details in setup.log
  goto end
)
echo Creating shortcuts (Desktop, Start menu, start with Windows)...
".venv\Scripts\python.exe" flowtype.py --make-icon >> "%LOG%" 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d='%~dp0'; $w=New-Object -ComObject WScript.Shell; foreach($p in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Startup'))){ $s=$w.CreateShortcut($p+'\FlowType.lnk'); $s.TargetPath=$d+'.venv\Scripts\pythonw.exe'; $s.Arguments='\"'+$d+'flowtype.py\"'; $s.WorkingDirectory=$d; $s.IconLocation=$d+'flowtype.ico'; $s.Description='FlowType voice typing'; $s.Save() }" >> "%LOG%" 2>&1
echo SETUP OK >> "%LOG%"
echo.
echo === Done! Starting FlowType... ===
echo Hold Ctrl+Alt, speak, release.  Ctrl+Shift+Space = hands-free.
echo Right-click the mic icon near the clock to pick Odia / Hindi and "English letters".
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*flowtype.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
start "" ".venv\Scripts\pythonw.exe" "%~dp0flowtype.py"
goto end

:pipfail
if defined RETRIED (
  echo [X] Package install failed. See setup.log
  goto end
)
set "RETRIED=1"
echo Packages don't support this Python version - switching to Python 3.12...
echo --- retrying with Python 3.12 >> "%LOG%"
set "PYEXE="
call :find312
if not defined PYEXE call :install312
if not defined PYEXE (
  echo [X] Could not install Python 3.12. See setup.log
  goto end
)
rmdir /s /q .venv
goto makevenv

:findpython
call :find312
if defined PYEXE exit /b 0
for %%V in (3.11 3.13 3.10 3.14) do (
  if not defined PYEXE (
    for /f "delims=" %%E in ('py -%%V -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%E"
  )
)
if not defined PYEXE (
  for /f "delims=" %%E in ('python -c "import sys;assert sys.version_info[:2]>=(3,10);print(sys.executable)" 2^>nul') do set "PYEXE=%%E"
)
for %%P in ("%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "C:\Python313\python.exe" "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" "C:\Python314\python.exe") do (
  if not defined PYEXE if exist "%%~P" set "PYEXE=%%~P"
)
exit /b 0

:find312
for /f "delims=" %%E in ('py -3.12 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%E"
for %%P in ("%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "C:\Python312\python.exe" "C:\Program Files\Python312\python.exe") do (
  if not defined PYEXE if exist "%%~P" set "PYEXE=%%~P"
)
exit /b 0

:install312
echo Installing Python 3.12 (one time)...
winget install -e --id Python.Python.3.12 --scope user --silent --accept-source-agreements --accept-package-agreements >> "%LOG%" 2>&1
call :find312
exit /b 0

:end
echo.
pause
