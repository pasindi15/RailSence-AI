@echo off
REM Starts the M1 backend using the project's venv explicitly, so it never
REM silently falls back to a global Python (which has an older, incompatible
REM chromadb and breaks RAG retrieval with KeyError: '_type').
REM
REM Usage: run.bat [port]

setlocal
set "SCRIPT_DIR=%~dp0"
set "VENV_PYTHON=%SCRIPT_DIR%venv\Scripts\python.exe"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8010"

if not exist "%VENV_PYTHON%" (
    echo venv not found at %VENV_PYTHON%
    echo Run from backend\: python -m venv venv ^&^& venv\Scripts\python -m pip install -r requirements.txt
    exit /b 1
)

cd /d "%SCRIPT_DIR%"
"%VENV_PYTHON%" -m uvicorn main:app --reload --port %PORT%
