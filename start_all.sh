#!/bin/bash
# RailSense AI - Start All Services (macOS)
# Uses 9xxx ports to avoid conflicts with other projects

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── Port definitions ─────────────────────────────────────────────────────────
M1_PORT=9001
HUB_PORT=9002
BOOKING_PORT=9003
SECURITY_PORT=9004
M2_PORT=9005
M4_PORT=8006
GATEWAY_PORT=4000
REACT_PORT=5280
M4_LOGIN_PORT=3002

# ── Derived URLs (passed as env overrides so .env files are untouched) ────────
HUB_URL="http://localhost:$HUB_PORT"
M1_URL="http://localhost:$M1_PORT"
M2_URL="http://localhost:$M2_PORT"
M3_URL="http://localhost:$BOOKING_PORT"
M4_URL="http://localhost:$M4_PORT"
SECURITY_URL="http://localhost:$SECURITY_PORT"

echo "\033[36mStarting RailSense AI (alternate ports — no conflict mode)...\033[0m"

# 1. M1 Passenger Assistant (9001)
osascript -e "tell app \"Terminal\" to do script \"cd '$ROOT/M1-passenger_assistant/backend' && AGENT_HUB_URL=$HUB_URL '$ROOT/M1-passenger_assistant/backend/venv/bin/python' -m uvicorn main:app --host 127.0.0.1 --port $M1_PORT --reload\""

# 2. M2 Operations Agent (9005)
osascript -e "tell app \"Terminal\" to do script \"cd '$ROOT/M2-operations-agent' && AGENT_HUB_URL=$HUB_URL python -m uvicorn main:app --host 127.0.0.1 --port $M2_PORT --reload\""

# 3. M3 Communication Hub (9002)
M3_DIR="$ROOT/M3-Comunication-Hub&Booking-Agent"
osascript -e "tell app \"Terminal\" to do script \"cd '$M3_DIR/agent-hub' && DATABASE_URL=sqlite:///./railsense_hub_audit.db PASSENGER_AGENT_URL=$M1_URL BOOKING_AGENT_URL=$M3_URL SECURITY_AGENT_URL=$SECURITY_URL OPERATIONS_AGENT_URL=$M2_URL MAINTENANCE_AGENT_URL=$M4_URL python -m uvicorn main:app --host 127.0.0.1 --port $HUB_PORT --reload\""

# 4. M3 Booking Agent (9003)
osascript -e "tell app \"Terminal\" to do script \"cd '$M3_DIR/booking-agent' && AGENT_HUB_URL=$HUB_URL APP_PORT=$BOOKING_PORT python -m uvicorn main:app --host 127.0.0.1 --port $BOOKING_PORT --reload\""

# 5. Security & Fraud Agent (9004)
osascript -e "tell app \"Terminal\" to do script \"cd '$ROOT/security-agent' && AGENT_HUB_URL=$HUB_URL python -m uvicorn main:app --host 127.0.0.1 --port $SECURITY_PORT --reload\""

# 6. M4 Maintenance Agent (8006)
osascript -e "tell app \"Terminal\" to do script \"cd '$ROOT/M4-maintenance-agent' && MAINTENANCE_AGENT_URL=$M4_URL MAINTENANCE_AGENT_PORT=$M4_PORT python -m uvicorn main:app --host 127.0.0.1 --port $M4_PORT --reload\""

# 7. Unified Frontend Gateway (4000)
osascript -e "tell app \"Terminal\" to do script \"cd '$ROOT/frontend' && PORT=$GATEWAY_PORT python serve.py\""

# 8. M1 React App (5274)
osascript -e "tell app \"Terminal\" to do script \"cd '$ROOT/M1-passenger_assistant/frontend' && npm run dev -- --port $REACT_PORT\""

# 9. M4 Login Portal — Next.js (3002)
osascript -e "tell app \"Terminal\" to do script \"cd '$ROOT/M4-maintenance-agent/frontend' && NEXT_PUBLIC_M4_URL=http://localhost:$M4_PORT npm run dev -- --port $M4_LOGIN_PORT\""

echo "\033[32mAll services launched!\033[0m"
echo ""
echo "  M1 Passenger Chat:  http://localhost:$REACT_PORT"
echo "  User Portal:        http://localhost:$GATEWAY_PORT/user"
echo "  Admin Portal:       http://localhost:$GATEWAY_PORT/admin"
echo "  M3 Hub:             http://localhost:$HUB_PORT"
echo "  M4 Maintenance:     http://localhost:$M4_PORT"
echo "  M4 Login (robot):   http://localhost:$M4_LOGIN_PORT"
echo ""
echo "  (M1=$M1_PORT  M2=$M2_PORT  Hub=$HUB_PORT  Booking=$BOOKING_PORT  Security=$SECURITY_PORT  M4=$M4_PORT  M4-Login=$M4_LOGIN_PORT)"
