@echo off
title RailSense AI
rem The backend and both portal sides now start together from one launcher (start.py),
rem so every agent and page agrees on the ports. See start_all.bat.
cd /d "%~dp0"
where python >nul 2>nul && (python start.py %*) || (py -3 start.py %*)
pause
