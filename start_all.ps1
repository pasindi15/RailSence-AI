# RailSense AI - Start All Services (PowerShell)
# Launches all 7 multi-agent ecosystem services in their own terminal windows

$root = $PSScriptRoot

Write-Host "Starting RailSense AI Multi-Agent Ecosystem..." -ForegroundColor Cyan

# 1. M1 Passenger Assistant (Port 8001)
# Uses the backend's own venv (not the system `python` on PATH) - its
# chromadb version must match the one that built .chroma/chroma.sqlite3,
# or RAG lookups fail with "TypeError: object of type 'int' has no len()"
# and every fare/schedule/train-details question silently falls back to
# "I'm having trouble looking that up right now."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\M1-passenger_assistant\backend'; Write-Host 'Starting M1 Passenger Assistant on port 8001...' -ForegroundColor Cyan; .\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload"

# 2. M2 Operations Agent (Port 8005)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\M2-operations-agent'; Write-Host 'Starting M2 Operations Agent on port 8005...' -ForegroundColor DarkCyan; python -m uvicorn main:app --host 127.0.0.1 --port 8005 --reload"

# 3. M3 Communication Hub (Port 8002)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\M3-Comunication-Hub&Booking-Agent\agent-hub'; Write-Host 'Starting M3 Communication Hub on port 8002...' -ForegroundColor Blue; python -m uvicorn main:app --host 127.0.0.1 --port 8002 --reload"

# 4. M3 Booking Agent (Port 8003)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\M3-Comunication-Hub&Booking-Agent\booking-agent'; Write-Host 'Starting M3 Booking Agent on port 8003...' -ForegroundColor Green; python -m uvicorn main:app --host 127.0.0.1 --port 8003 --reload"

# 5. Security & Fraud Agent (Port 8004)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\security-agent'; Write-Host 'Starting Security & Fraud Agent on port 8004...' -ForegroundColor Yellow; python -m uvicorn main:app --host 127.0.0.1 --port 8004 --reload"

# 6. M4 Maintenance Agent (Port 8006)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\M4-maintenance-agent'; Write-Host 'Starting M4 Maintenance Agent on port 8006...' -ForegroundColor DarkYellow; python -m uvicorn main:app --host 127.0.0.1 --port 8006 --reload"

# 7. Unified Frontend Gateway (Port 3000)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; Write-Host 'Starting RailSense Gateway on port 3000...' -ForegroundColor Magenta; python serve.py"

# 8. M1 React App (Port 5173)
Start-Process cmd -ArgumentList "/k", "cd /d `"$root\M1-passenger_assistant\frontend`" && npm.cmd run dev"

Write-Host "`nAll RailSense AI services launched in separate windows!" -ForegroundColor Green
Write-Host "User Portal:       http://localhost:3000/user" -ForegroundColor Cyan
Write-Host "Admin Portal:      http://localhost:3000/admin" -ForegroundColor Yellow
Write-Host "M1 React Chat App: http://localhost:5173" -ForegroundColor Green

