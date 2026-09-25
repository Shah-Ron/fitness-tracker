@echo off
title Fitness Tracker - build the .exe
cd /d "%~dp0\.."

rem Stop a running copy so the exe is not held open.
curl -s -X POST http://127.0.0.1:8778/api/stop >nul 2>&1
timeout /t 2 /nobreak >nul

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo Could not install PyInstaller.
        pause
        exit /b 1
    )
)

echo Drawing the icon...
python tools\make_icon.py
if errorlevel 1 (
    echo The icon script failed.
    pause
    exit /b 1
)

echo Building...
python -m PyInstaller --noconfirm --onefile --noconsole ^
    --name "Fitness Tracker" ^
    --icon "%CD%\tools\icon.ico" ^
    --add-data "%CD%\app.html;." ^
    --add-data "%CD%\sw.js;." ^
    --add-data "%CD%\manifest.webmanifest;." ^
    --add-data "%CD%\icon-192.png;." ^
    --add-data "%CD%\icon-512.png;." ^
    --add-data "%CD%\icon-maskable-512.png;." ^
    --add-data "%CD%\data;data" ^
    --distpath . ^
    --workpath "%TEMP%\fitness-tracker-build" ^
    --specpath "%TEMP%\fitness-tracker-build" ^
    fitness_tracker.py
if errorlevel 1 (
    echo.
    echo The build failed. Read the messages above.
    pause
    exit /b 1
)

echo.
echo Done. "Fitness Tracker.exe" is in this folder. Double-click it to start.
pause
