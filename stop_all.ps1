# RailSense AI - Stop All Services (PowerShell)
# Gracefully and completely terminates all RailSense AI services and their child workers

Write-Host "Stopping all RailSense AI processes..." -ForegroundColor Yellow

$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
$killed = 0

foreach ($p in $procs) {
    $cmd = $p.CommandLine
    if ($cmd -and ($cmd -match 'uvicorn' -or $cmd -match 'serve\.py' -or $cmd -match 'multiprocessing\.spawn' -or $cmd -match 'railsense')) {
        # Never kill language server / editor extensions
        if ($cmd -notmatch 'language-server' -and $cmd -notmatch 'jedi') {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                Write-Host "  Terminated PID $($p.ProcessId)" -ForegroundColor Green
                $killed++
            } catch {}
        }
    }
}

# Also kill node for frontend react
$nodeProcs = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue
foreach ($np in $nodeProcs) {
    if ($np.CommandLine -match 'vite' -or $np.CommandLine -match 'M1-passenger_assistant') {
        try {
            Stop-Process -Id $np.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "  Terminated Node PID $($np.ProcessId)" -ForegroundColor Green
            $killed++
        } catch {}
    }
}

Write-Host "`nRailSense AI services completely stopped ($killed processes terminated)." -ForegroundColor Cyan
