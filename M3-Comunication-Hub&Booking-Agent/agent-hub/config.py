"""
agent-hub/config.py
-------------------
RailSense AI — Agent Communication Hub Configuration
Central configuration loaded from environment variables (and .env file).

Architectural rules:
- Reads settings from environment variables with safe development defaults.
- JWT_SECRET_KEY must NOT have a real production secret hardcoded in source code.
- Downstream agent URLs are loaded for the routing pipeline.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# ── Service binding ───────────────────────────────────────────────────────────
APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT: int = int(os.getenv("APP_PORT", "8002"))

# ── JWT Authentication ────────────────────────────────────────────────────────
# In production, set JWT_SECRET_KEY via environment variable or secret manager.
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")

# ── Downstream agent service URLs ─────────────────────────────────────────────
PASSENGER_AGENT_URL: str = os.getenv("PASSENGER_AGENT_URL", "http://localhost:8001")
BOOKING_AGENT_URL: str = os.getenv("BOOKING_AGENT_URL", "http://localhost:8003")
SECURITY_AGENT_URL: str = os.getenv("SECURITY_AGENT_URL", "http://localhost:8004")
OPERATIONS_AGENT_URL: str = os.getenv("OPERATIONS_AGENT_URL", "http://localhost:8005")
MAINTENANCE_AGENT_URL: str = os.getenv("MAINTENANCE_AGENT_URL", "http://localhost:8006")

# ── Database / Audit Persistence ──────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")
