#!/usr/bin/env bash
# RailSense AI - start everything (macOS / Linux).
# Same launcher and same ports as Windows (railsense_ports.json). If a port is taken by
# another program, start.py moves to the next free one and tells every service and page.
#   User side:  http://localhost:3000/user      Admin side: http://localhost:3001/admin
cd "$(dirname "$0")"
exec python3 start.py "$@"
