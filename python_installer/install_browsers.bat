@echo off
REM ============================================================
REM Install Playwright Browsers (Corporate Network)
REM ============================================================
REM Use this if the standard install fails due to SSL/certificate issues.
REM This bypasses certificate verification for the download.
REM ============================================================

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%SCRIPT_DIR%python_bin\python.exe"

echo Installing Playwright browsers with SSL bypass...
echo.

REM Set environment variable to bypass SSL verification
set NODE_TLS_REJECT_UNAUTHORIZED=0

REM Run playwright install
"%PYTHON_EXE%" -m playwright install chromium

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Playwright browsers installed successfully!
) else (
    echo.
    echo Installation failed. Try running as Administrator.
)

pause
