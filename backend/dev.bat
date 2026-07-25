@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [error] venv not found. Create it first: python -m venv venv
    pause
    exit /b 1
)

set "PY=%~dp0venv\Scripts\python.exe"
set "UVICORN=%~dp0venv\Scripts\uvicorn.exe"

echo Starting backend dev server...
echo Stop: Ctrl+C once; if still stuck after 3s, press Ctrl+C again.
echo.

REM Only stop python/uvicorn on :8000 (do not kill Docker etc.)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    for /f "tokens=1" %%p in ('tasklist /FI "PID eq %%a" /FO CSV /NH 2^>nul') do (
        set "PROC=%%~p"
        if /I "!PROC!"=="python.exe" (
            echo Stopping leftover python on :8000 PID=%%a
            taskkill /F /PID %%a >nul 2>&1
        ) else if /I "!PROC!"=="uvicorn.exe" (
            echo Stopping leftover uvicorn on :8000 PID=%%a
            taskkill /F /PID %%a >nul 2>&1
        ) else (
            echo Skip non-python listener on :8000 PID=%%a ^(!PROC!^)
        )
    )
)
timeout /t 1 /nobreak >nul

"%PY%" -m scripts.run_migrations
if errorlevel 1 (
    echo Migration failed. See log above.
    pause
    exit /b 1
)

"%UVICORN%" app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app --reload-delay 1.0 --timeout-graceful-shutdown 3
