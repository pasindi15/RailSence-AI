@echo off
title RailSense AI Launcher
echo Starting RailSense AI Services...

start "Security Agent (Port 8004)" cmd /k "cd /d "%~dp0security-agent" && python -m uvicorn main:app --host 127.0.0.1 --port 8004 --reload"

start "Booking Agent (Port 8003)" cmd /k "cd /d "%~dp0M3-Comunication-Hub&Booking-Agent\booking-agent" && python -m uvicorn main:app --host 127.0.0.1 --port 8003 --reload"

start "Communication Hub (Port 8002)" cmd /k "cd /d "%~dp0M3-Comunication-Hub&Booking-Agent\agent-hub" && python -m uvicorn main:app --host 127.0.0.1 --port 8002 --reload"

start "Frontend & Gateway (Port 3000)" cmd /k "cd /d "%~dp0frontend" && python serve.py"

echo All services launched!
echo Access RailSense at http://localhost:3000
pause
