@echo off
title RailSense AI Multi-Agent Ecosystem Launcher
echo Starting RailSense AI Multi-Agent Ecosystem...

start "M1 Passenger Assistant (Port 8001)" cmd /k "cd /d "%~dp0M1-passenger_assistant\backend" && python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload"

start "M2 Operations Agent (Port 8005)" cmd /k "cd /d "%~dp0M2-operations-agent" && python -m uvicorn main:app --host 127.0.0.1 --port 8005 --reload"

start "M3 Communication Hub (Port 8002)" cmd /k "cd /d "%~dp0M3-Comunication-Hub&Booking-Agent\agent-hub" && python -m uvicorn main:app --host 127.0.0.1 --port 8002 --reload"

start "M3 Booking Agent (Port 8003)" cmd /k "cd /d "%~dp0M3-Comunication-Hub&Booking-Agent\booking-agent" && python -m uvicorn main:app --host 127.0.0.1 --port 8003 --reload"

start "Security Agent (Port 8004)" cmd /k "cd /d "%~dp0security-agent" && python -m uvicorn main:app --host 127.0.0.1 --port 8004 --reload"

start "M4 Maintenance Agent (Port 8006)" cmd /k "cd /d "%~dp0M4-maintenance-agent" && python -m uvicorn main:app --host 127.0.0.1 --port 8006 --reload"

start "Frontend Gateway (Port 3000)" cmd /k "cd /d "%~dp0frontend" && python serve.py"

echo All 7 RailSense services launched!
echo User Portal:  http://localhost:3000/user
echo Admin Portal: http://localhost:3000/admin
pause

