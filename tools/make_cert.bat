@echo off
title Fitness Tracker - make certificates
cd /d "%~dp0\.."

python -c "import cryptography" >nul 2>&1
if errorlevel 1 (
    echo Installing the cryptography package, one time only...
    python -m pip install "cryptography>=42"
    if errorlevel 1 (
        echo Could not install cryptography. Check that Python and pip work, then try again.
        pause
        exit /b 1
    )
)

python tools\make_cert.py
if errorlevel 1 (
    echo.
    echo Something went wrong. Read the message above.
    pause
    exit /b 1
)

rem Tell a running copy of the app to pick the new certificate up.
curl -s -X POST http://127.0.0.1:8778/api/phone/reload-cert >nul 2>&1

echo.
pause
