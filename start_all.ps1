# RailSense AI - start everything (PowerShell).
# One launcher for every laptop: start.py chooses the ports (railsense_ports.json),
# frees ports an earlier RailSense run left behind, and starts all agents + both portal sides.
#   User side:  http://localhost:3000/user      Admin side: http://localhost:3001/admin
Set-Location $PSScriptRoot
if (Get-Command python -ErrorAction SilentlyContinue) { python start.py @args } else { py -3 start.py @args }
