@echo off
REM Use this batch file to run your python scripts using the portable environment.
REM Keeps you from having to mess with system PATH.

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%SCRIPT_DIR%python_bin\python.exe"

REM EXAMPLE: Run a script named 'main.py' located in the same folder
REM "%PYTHON_EXE%" "%SCRIPT_DIR%main.py"

REM Checks python version to verify installation
echo Python Environment:
"%PYTHON_EXE%" --version
echo.
echo To run your script, edit this file and uncomment the line below:
echo "%PYTHON_EXE%" "your_script.py"
pause
