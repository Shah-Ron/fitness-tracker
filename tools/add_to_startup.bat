@echo off
title Fitness Tracker - start with Windows
cd /d "%~dp0\.."

if not exist "Fitness Tracker.exe" (
    echo Build the .exe first with tools\build_exe.bat.
    pause
    exit /b 1
)

set "LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Fitness Tracker.lnk"
powershell -NoProfile -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%LINK%');" ^
  "$s.TargetPath = '%CD%\Fitness Tracker.exe';" ^
  "$s.Arguments = '--no-browser';" ^
  "$s.WorkingDirectory = '%CD%';" ^
  "$s.IconLocation = '%CD%\tools\icon.ico';" ^
  "$s.Description = 'Fitness Tracker server, so the phone can sync';" ^
  "$s.Save()"
if errorlevel 1 (
    echo Could not create the shortcut.
    pause
    exit /b 1
)

echo Done. Fitness Tracker will start quietly when you sign in to Windows.
echo To undo, delete this file:
echo   %LINK%
pause
