# RailSense AI - Start All Services (PowerShell)
# Launches all 7 multi-agent ecosystem services in their own terminal windows

$root = $PSScriptRoot

Write-Host "Stopping any lingering RailSense AI processes..." -ForegroundColor Yellow
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
foreach ($p in $procs) {
    $cmd = $p.CommandLine
    if ($cmd -and ($cmd -match 'uvicorn' -or $cmd -match 'serve\.py' -or $cmd -match 'multiprocessing\.spawn')) {
        if ($cmd -notmatch 'language-server' -and $cmd -notmatch 'jedi') {
            try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
}
$nodeProcs = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue
foreach ($np in $nodeProcs) {
    if ($np.CommandLine -match 'vite' -or $np.CommandLine -match 'M1-passenger_assistant') {
        try { Stop-Process -Id $np.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
    }
}
Start-Sleep -Seconds 1

Write-Host "Starting RailSense AI Multi-Agent Ecosystem..." -ForegroundColor Cyan

# 1. M1 Passenger Assistant (Port 8001)
$m1Dir = Join-Path $root "M1-passenger_assistant\backend"
$m1Cmd = "Write-Host 'Starting M1 Passenger Assistant on port 8001...' -ForegroundColor Cyan; if (Test-Path '.\venv\Scripts\python.exe') { .\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload } else { python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload }"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $m1Cmd -WorkingDirectory $m1Dir

# 2. M2 Operations Agent (Port 8005)
$m2Dir = Join-Path $root "M2-operations-agent"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Starting M2 Operations Agent on port 8005...' -ForegroundColor DarkCyan; python -m uvicorn main:app --host 127.0.0.1 --port 8005 --reload" -WorkingDirectory $m2Dir

# 3. M3 Communication Hub (Port 8002)
$m3HubDir = Join-Path $root "M3-Comunication-Hub&Booking-Agent\agent-hub"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Starting M3 Communication Hub on port 8002...' -ForegroundColor Blue; python -m uvicorn main:app --host 127.0.0.1 --port 8002 --reload" -WorkingDirectory $m3HubDir

# 4. M3 Booking Agent (Port 8003)
$m3BookingDir = Join-Path $root "M3-Comunication-Hub&Booking-Agent\booking-agent"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Starting M3 Booking Agent on port 8003...' -ForegroundColor Green; python -m uvicorn main:app --host 127.0.0.1 --port 8003 --reload" -WorkingDirectory $m3BookingDir

# 5. Security & Fraud Agent (Port 8004)
$secDir = Join-Path $root "security-agent"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Starting Security & Fraud Agent on port 8004...' -ForegroundColor Yellow; python -m uvicorn main:app --host 127.0.0.1 --port 8004 --reload" -WorkingDirectory $secDir

# 6. M4 Maintenance Agent (Port 8006)
$m4Dir = Join-Path $root "M4-maintenance-agent"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Starting M4 Maintenance Agent on port 8006...' -ForegroundColor DarkYellow; python -m uvicorn main:app --host 127.0.0.1 --port 8006 --reload" -WorkingDirectory $m4Dir

# 7a. Build the M1 React chat app so the gateway can serve it at /user/chat
$reactDir = Join-Path $root "M1-passenger_assistant\frontend"
Write-Host "Building M1 chat app..." -ForegroundColor Green
Push-Location $reactDir; npm.cmd run build; Pop-Location

# 7. Unified Frontend Gateway (Port 3000)
$frontendDir = Join-Path $root "frontend"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Starting RailSense Gateway on port 3000...' -ForegroundColor Magenta; python serve.py" -WorkingDirectory $frontendDir

# 8. M4 Maintenance Login Portal (Port 3002)
$m4FrontendDir = Join-Path $root "M4-maintenance-agent\frontend"
Start-Process cmd -ArgumentList "/k", "npm.cmd run dev" -WorkingDirectory $m4FrontendDir

Write-Host "`nAll RailSense AI services launched in separate windows!" -ForegroundColor Green
Write-Host "User Portal:       http://localhost:3000/user" -ForegroundColor Cyan
Write-Host "Admin Portal:      http://localhost:3000/admin" -ForegroundColor Yellow
Write-Host "M1 React Chat App: http://localhost:3000/user/chat" -ForegroundColor Green
Write-Host "M4 Login Portal:   http://localhost:3002" -ForegroundColor DarkYellow
