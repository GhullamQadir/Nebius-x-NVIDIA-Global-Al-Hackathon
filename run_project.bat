@echo off
setlocal enabledelayedexpansion
title Nexora AI Platform - Runner
cd /d "%~dp0"

echo ==============================================================================
echo                      NEXORA AI CODING AGENT PLATFORM
echo ==============================================================================
echo.

:: 1. Check Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ and add it to your System PATH.
    exit /b 1
)

:: 2. Terminate any previous processes on port 8001 and 3000
echo [1/6] Stopping any existing Nexora servers on ports 8001 and 3000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8001 ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :3000 ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

:: 3. Activate virtual environment if present
echo [2/6] Activating Python virtual environment (if present)...
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo       -> Using venv
) else if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo       -> Using .venv
) else (
    echo       -> No venv found, using system Python
)

:: 4. Install/Update dependencies
echo [3/6] Installing/Updating Python dependencies...
pip install -r nexora\backend\requirements.txt >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] Failed to install some dependencies, continuing anyway...
)

:: 5. Seed demo database
echo [4/6] Ensuring database and model registry are seeded...
python seed_demo_data.py >nul 2>&1

:: 6. Start Backend API
echo [5/6] Starting Nexora Backend API on http://127.0.0.1:8001 ...
start "Nexora-Backend" cmd /k "cd /d "%~dp0" && title Nexora-Backend && python -m uvicorn nexora.backend.app.main:app --host 127.0.0.1 --port 8001 --reload"

:: Wait for backend to be ready
echo Waiting for Backend API to initialize...
timeout /t 5 /nobreak >nul

:: Quick health check
echo [6/6] Verifying Backend health...
powershell -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/api/v1/health' -TimeoutSeconds 10; if ($r.status -eq 'healthy') { Write-Host '[OK] Backend is healthy' } else { Write-Host '[WARN] Backend responded but status unexpected' } } catch { Write-Host '[WARN] Backend not reachable yet, continuing...' }"

:: 7. Start Frontend UI & Reverse Proxy
echo.
echo Starting Nexora Frontend UI on http://127.0.0.1:3000 ...
start "Nexora-Frontend" cmd /k "cd /d "%~dp0" && title Nexora-Frontend && python scripts/dev_server.py --port 3000 --api-port 8001"

timeout /t 3 /nobreak >nul

:: 8. Launch browser
start http://127.0.0.1:3000

echo.
echo ==============================================================================
echo   NEXORA IS NOW LIVE AND READY!
echo ==============================================================================
echo.
echo   PREVIEW LINKS (click or copy to browser):
echo   -----------------------------------------
echo    > Web UI (Main App)      : http://127.0.0.1:3000
echo    > Backend API (Swagger)  : http://127.0.0.1:8001/docs
echo    > Backend Health Check   : http://127.0.0.1:8001/api/v1/health
echo    > Backend ReDoc          : http://127.0.0.1:8001/redoc
echo   -----------------------------------------
echo.
echo   QUICK TEST COMMANDS:
echo   -----------------------------------------
echo   Test run creation: curl -X POST http://127.0.0.1:8001/api/v1/runs -H "Content-Type: application/json" -d "{\"workspace_id\": \"00000000-0000-0000-0000-000000000001\", \"task_text\": \"Create a simple calculator in Python\"}"
echo   -----------------------------------------
echo.
echo Servers are running in background minimized windows.
echo Use stop_project.bat to stop them when done.
echo.
echo Press any key to keep this window open for log viewing...
pause >nul