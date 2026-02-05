@echo off
REM ============================================================
REM Run Driver (Silent) - For Task Scheduler
REM ============================================================
REM Use this version for Windows Task Scheduler to run without
REM showing a command window.
REM ============================================================

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%SCRIPT_DIR%python_installer\python_bin\python.exe"
set "DRIVER_SCRIPT=%SCRIPT_DIR%driver.py"

if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%DRIVER_SCRIPT%"
)
