@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_checks.ps1"
set "VN30_EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %VN30_EXIT_CODE%

