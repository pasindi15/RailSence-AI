@echo off
title RailSense AI - M1 Passenger Assistant Launcher
echo =======================================================
echo Starting M1 Passenger Assistant (Backend + React App)
echo =======================================================
echo.

start "M1 Backend (Port 8001)" cmd /k "cd /d "%~dp0M1-passenger_assistant\backend" && python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload"
start "M1 React App (Port 5173)" cmd /k "cd /d "%~dp0M1-passenger_assistant\frontend" && npm.cmd run dev"

echo.
echo Both M1 services started!
echo M1 Backend:   http://localhost:8001
echo M1 React App: http://localhost:5173
echo.
pause
