@echo off
chcp 65001 >nul
cd /d %~dp0
call venv\Scripts\activate

echo Starting backend dev server...
echo Stop: Ctrl+C once; if still stuck after 3s, press Ctrl+C again.
echo.

REM 释放 8000 端口上残留的 uvicorn，避免 SQLite database is locked
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo Stopping leftover process on :8000 PID=%%a
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

python -m scripts.run_migrations
if errorlevel 1 (
    echo Migration failed. See log above.
    pause
    exit /b 1
)

uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app --reload-delay 1.0 --timeout-graceful-shutdown 3
