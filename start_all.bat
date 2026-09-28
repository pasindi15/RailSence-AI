@echo off
title RailSense AI
rem One launcher for every laptop: see start.py (ports come from railsense_ports.json).
rem   User side:  http://localhost:3000/user     Admin side: http://localhost:3001/admin
cd /d "%~dp0"
where python >nul 2>nul && (python start.py %*) || (py -3 start.py %*)
pause
