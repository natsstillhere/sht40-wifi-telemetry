@echo off
setlocal
cd /d "%~dp0"
set "PYTHONW=%~dp0server\.venv\Scripts\pythonw.exe"
if not exist "%PYTHONW%" (
    echo Project Python environment not found.
    echo Run the Windows setup commands in README.md first.
    pause
    exit /b 1
)
start "" "%PYTHONW%" "%~dp0telemetry_launcher.py"