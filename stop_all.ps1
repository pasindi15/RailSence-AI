# RailSense AI - stop everything this repository started (and nothing else).
Set-Location $PSScriptRoot
if (Get-Command python -ErrorAction SilentlyContinue) { python start.py --stop } else { py -3 start.py --stop }
