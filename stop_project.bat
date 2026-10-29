@echo off
title Nexora AI Platform - Stopper
cd /d "%~dp0"

echo ==============================================================================
echo                      STOPPING NEXORA PLATFORM
echo ==============================================================================
echo.

echo [1/3] Terminating processes on Port 8001 (Backend API)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8001 ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1
    echo       -> Killed PID %%a
)

echo [2/3] Terminating processes on Port 3000 (Frontend & Proxy)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :3000 ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1
    echo       -> Killed PID %%a
)

echo [3/3] Cleaning up any remaining Nexora cmd windows...
taskkill /f /fi "WINDOWTITLE eq Nexora-Backend*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq Nexora-Frontend*" >nul 2>&1

echo.
echo ==============================================================================
echo   ALL NEXORA SERVERS STOPPED SUCCESSFULLY
echo ==============================================================================
echo.
timeout /t 2 /nobreak >nul
exit /b 0