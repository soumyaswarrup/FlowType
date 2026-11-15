@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d='%~dp0'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\FlowType.lnk'); $s.TargetPath=$d+'.venv\Scripts\pythonw.exe'; $s.Arguments='\"'+$d+'flowtype.py\"'; $s.WorkingDirectory=$d; $s.Save()"
echo FlowType will now start automatically when you sign in to Windows.
pause
