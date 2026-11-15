@echo off
setlocal
cd /d "%~dp0"
title Building FlowType.exe
set "LOG=%~dp0build.log"
echo Build started %date% %time% > "%LOG%"
echo Building FlowType.exe for sharing - takes 3-8 minutes...

if not exist ".venv\Scripts\python.exe" ( echo Run setup.bat first. & echo BUILD FAILED no venv >> "%LOG%" & pause & exit /b 1 )
if not exist "flowtype.ico" ".venv\Scripts\python.exe" flowtype.py --make-icon >> "%LOG%" 2>&1

echo [1/4] Installing the packager...
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller >> "%LOG%" 2>&1

echo [2/4] Packaging the app...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name FlowType ^
  --icon flowtype.ico ^
  --collect-data faster_whisper ^
  --collect-binaries ctranslate2 ^
  --hidden-import pystray._win32 ^
  flowtype.py >> "%LOG%" 2>&1
if not exist "dist\FlowType\FlowType.exe" ( echo [X] Packaging failed - see build.log & echo BUILD FAILED >> "%LOG%" & pause & exit /b 1 )

echo [3/4] Testing the packaged app...
start "" /wait "dist\FlowType\FlowType.exe" --selftest "%~dp0selftest.txt"
type selftest.txt >> "%LOG%"
findstr /c:"SELFTEST OK" selftest.txt >nul || ( echo [X] Self-test failed - see build.log & echo BUILD FAILED selftest >> "%LOG%" & pause & exit /b 1 )

echo [4/4] Zipping...
copy /y "SHARE-README.txt" "dist\FlowType\HOW TO INSTALL.txt" >nul
powershell -NoProfile -Command "Compress-Archive -Path 'dist\FlowType' -DestinationPath 'dist\FlowType-Windows.zip' -Force" >> "%LOG%" 2>&1
echo BUILD OK >> "%LOG%"
echo.
echo === Done! Share this file: dist\FlowType-Windows.zip ===
explorer "dist"
pause
