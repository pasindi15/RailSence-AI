# Starts the M1 backend using the project's venv explicitly, so it never
# silently falls back to a global Python (which has an older, incompatible
# chromadb and breaks RAG retrieval with KeyError: '_type').
#
# Usage: .\run.ps1 [-Port 8010]

param(
    [int]$Port = 8010
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ScriptDir "venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "venv not found at $VenvPython. Run from backend\: python -m venv venv; venv\Scripts\python -m pip install -r requirements.txt"
    exit 1
}

Set-Location $ScriptDir
& $VenvPython -m uvicorn main:app --reload --port $Port
