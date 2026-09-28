@echo off
title RailSense AI
rem The portals start together with the agents from one launcher (start.py), so the
rem user side (3000) and admin side (3001) always know where each agent is. See start_all.bat.
cd /d "%~dp0"
where python >nul 2>nul && (python start.py %*) || (py -3 start.py %*)
pause
