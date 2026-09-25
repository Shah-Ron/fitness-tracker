@echo off
title Fitness Tracker
cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 (
    py -3 fitness_tracker.py %*
    goto done
)
where python >nul 2>&1
if not errorlevel 1 (
    python fitness_tracker.py %*
    goto done
)

echo Python was not found.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH" during setup.
pause
exit /b 1

:done
echo.
echo The server has stopped. Your data is safe in fitness.db.
pause
