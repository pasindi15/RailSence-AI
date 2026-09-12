# RailSense AI - Start All Services (PowerShell)
# Launches all 4 services in their own terminal windows

$root = $PSScriptRoot

Write-Host "Starting RailSense AI Multi-Agent Services..." -ForegroundColor Cyan

# 1. Security & Fraud Agent (Port 8004)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\security-agent'; Write-Host 'Starting Security & Fraud Agent on port 8004...' -ForegroundColor Yellow; python -m uvicorn main:app --host 127.0.0.1 --port 8004 --reload"

# 2. Booking Agent (Port 8003)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\M3-Comunication-Hub&Booking-Agent\booking-agent'; Write-Host 'Starting Booking Agent on port 8003...' -ForegroundColor Green; python -m uvicorn main:app --host 127.0.0.1 --port 8003 --reload"

# 3. Communication Hub (Port 8002)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\M3-Comunication-Hub&Booking-Agent\agent-hub'; Write-Host 'Starting Communication Hub on port 8002...' -ForegroundColor Blue; python -m uvicorn main:app --host 127.0.0.1 --port 8002 --reload"

# 4. Frontend Web App & Gateway (Port 3000)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; Write-Host 'Starting Frontend Gateway on port 3000...' -ForegroundColor Magenta; python serve.py"

Write-Host "`nAll 4 services launched in separate windows!" -ForegroundColor Green
Write-Host "Access the UI at: http://localhost:3000" -ForegroundColor Cyan
