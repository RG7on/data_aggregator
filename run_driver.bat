@echo off
REM ============================================================
REM Run Driver - Execute the Snapshot Scraper
REM ============================================================
REM This batch file runs driver.py using the portable Python environment.
REM Schedule this file with Windows Task Scheduler for 5-minute intervals.
REM ============================================================

REM Get the directory where this script is located
set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%SCRIPT_DIR%python_installer\python_bin\python.exe"
set "DRIVER_SCRIPT=%SCRIPT_DIR%driver.py"

REM Check if Python exists
if not exist "%PYTHON_EXE%" (
    echo ERROR: Python not found at %PYTHON_EXE%
    echo Please run python_installer\install.bat first.
    exit /b 1
)

REM Run the driver
echo Starting Snapshot Scraper Driver...
echo Python: %PYTHON_EXE%
echo Driver: %DRIVER_SCRIPT%
echo.

"%PYTHON_EXE%" "%DRIVER_SCRIPT%"

REM Capture exit code
set "EXIT_CODE=%ERRORLEVEL%"

if %EXIT_CODE% EQU 0 (
    echo.
    echo Driver completed successfully.
) else (
    echo.
    echo Driver completed with errors. Exit code: %EXIT_CODE%
)

exit /b %EXIT_CODE%
