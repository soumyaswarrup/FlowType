@echo off
rem Optional: lets FlowType use an NVIDIA graphics card (text appears ~3-5x faster).
rem Needs an NVIDIA GPU with a recent driver. About 1 GB download.
cd /d "%~dp0..\.."
set "ROOT=%CD%\"
if not exist ".venv\Scripts\python.exe" ( echo Run setup.bat first. & pause & exit /b 1 )
echo Installing NVIDIA CUDA libraries for FlowType...
".venv\Scripts\python.exe" -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
if errorlevel 1 ( echo Install failed. & pause & exit /b 1 )
echo.
echo Done. Restart FlowType (FlowType.bat). The tray menu will say "Ready (GPU)" if it worked;
echo if your PC has no usable NVIDIA GPU, FlowType simply keeps using the CPU.
pause
