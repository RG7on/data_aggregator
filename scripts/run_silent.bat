@echo off
REM ============================================================
REM Run Data Aggregator (Silent) — for Task Scheduler
REM ============================================================
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "PYTHON_EXE=%PROJECT_DIR%\python_installer\python_bin\python.exe"
set "ENTRY=%PROJECT_DIR%\run.py"

if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%ENTRY%"
)
