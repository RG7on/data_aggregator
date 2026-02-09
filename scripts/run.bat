@echo off
REM ============================================================
REM Run Data Aggregator
REM ============================================================
REM Runs all enabled workers via run.py using the portable Python.
REM Schedule with Windows Task Scheduler for automated collection.
REM ============================================================

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "PYTHON_EXE=%PROJECT_DIR%\python_installer\python_bin\python.exe"
set "ENTRY=%PROJECT_DIR%\run.py"

if not exist "%PYTHON_EXE%" (
    echo ERROR: Python not found at %PYTHON_EXE%
    echo Please run python_installer\install.bat first.
    pause
    exit /b 1
)

echo [%date% %time%] Starting Data Aggregator...
"%PYTHON_EXE%" "%ENTRY%"
echo.
echo Done. Press any key to close.
pause >nul
