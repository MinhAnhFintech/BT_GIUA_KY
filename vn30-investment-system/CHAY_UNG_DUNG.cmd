@echo off
cd /d "%~dp0"
"%USERPROFILE%\.venv\Scripts\python.exe" -m uvicorn backend.app.api.main:app --host 127.0.0.1 --port 8000
pause
