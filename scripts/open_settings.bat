@echo off
REM ============================================================
REM Data Aggregator — Control Panel
REM ============================================================
REM Starts the settings server and opens the control panel UI.
REM The server provides API access for reading/writing config
REM files and viewing scrape history.
REM ============================================================

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "PYTHON=%PROJECT_DIR%\python_installer\python_bin\python.exe"

REM Check for portable Python, fall back to system Python
if exist "%PYTHON%" (
    echo Using portable Python: %PYTHON%
) else (
    set "PYTHON=python"
    echo Using system Python
)

cd /d "%PROJECT_DIR%"
echo Starting Data Aggregator Control Panel...
echo Press Ctrl+C to stop the server.
echo.
"%PYTHON%" settings_server.py
