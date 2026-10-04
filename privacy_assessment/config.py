"""
privacy_assessment/config.py
----------------------------
RailSense AI — Privacy and Data Leakage Assessment Configuration.
Module: IT3041 Information Retrieval and Web Analytics
Assigned Specialisation: Privacy and Data Leakage Assessment (Student 2)

This configuration file defines:
- Target endpoint addresses and agent ports
- Client abstraction (Live HTTP via httpx with fallback to FastAPI TestClient)
- Synthetic test identities and synthetic PII (strictly isolated from real data)
- Risk matrix computation (Impact x Likelihood)
- Safe evidence redaction utilities
"""

from __future__ import annotations

import os
import sys
import json
import socket
import re
from datetime import datetime, timezone, timedelta, date
from typing import Any, Dict, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Workspace Paths & Monorepo Root Resolution
# ---------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
EVIDENCE_DIR = os.path.join(BASE_DIR, "evidence")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
REPORT_DATA_DIR = os.path.join(BASE_DIR, "report_data")

for d in (EVIDENCE_DIR, RESULTS_DIR, REPORT_DATA_DIR):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# Agent Ports (Matching railsense_ports.json)
# ---------------------------------------------------------------------------
PORT_PASSENGER = int(os.getenv("PORT_PASSENGER", "8001"))
PORT_HUB = int(os.getenv("PORT_HUB", "8002"))
PORT_BOOKING = int(os.getenv("PORT_BOOKING", "8003"))
PORT_SECURITY = int(os.getenv("PORT_SECURITY", "8004"))
PORT_OPS = int(os.getenv("PORT_OPS", "8005"))
PORT_MAINTENANCE = int(os.getenv("PORT_MAINTENANCE", "8006"))
PORT_USER_PORTAL = int(os.getenv("PORT_USER_PORTAL", "3000"))
PORT_ADMIN_PORTAL = int(os.getenv("PORT_ADMIN_PORTAL", "3001"))

# Base URLs
HUB_BASE_URL = os.getenv("HUB_URL", f"http://127.0.0.1:{PORT_HUB}")
BOOKING_BASE_URL = os.getenv("BOOKING_URL", f"http://127.0.0.1:{PORT_BOOKING}")
PASSENGER_BASE_URL = os.getenv("PASSENGER_URL", f"http://127.0.0.1:{PORT_PASSENGER}")
OPS_BASE_URL = os.getenv("OPS_URL", f"http://127.0.0.1:{PORT_OPS}")
MAINTENANCE_BASE_URL = os.getenv("MAINTENANCE_URL", f"http://127.0.0.1:{PORT_MAINTENANCE}")

# ---------------------------------------------------------------------------
# Synthetic Identities (Safety Guarantee: Never uses real individuals)
# ---------------------------------------------------------------------------
USER_A_ID = "synthetic-user-a-it3041"
USER_A_NAME = "Alice Perera (Synthetic Tester)"
USER_A_EMAIL = "alice.synthetic@railsense-audit.local"
USER_A_NIC = "200012345678"
USER_A_PHONE = "+94771234567"

USER_B_ID = "synthetic-user-b-it3041"
USER_B_NAME = "Bob Silva (Synthetic Tester)"
USER_B_EMAIL = "bob.synthetic@railsense-audit.local"
USER_B_NIC = "199512345670"
USER_B_PHONE = "+94719876543"

TEST_TRAIN_ID = "PM-4082"
TEST_ORIGIN = "Colombo Fort"
TEST_DESTINATION = "Kandy"
TEST_SEAT_CLASS = "Second Class"
FUTURE_TRAVEL_DATE = (date.today() + timedelta(days=30)).isoformat()

# ---------------------------------------------------------------------------
# Risk Classification & Evaluation Matrix
# ---------------------------------------------------------------------------
SEVERITY_CRITICAL = "Critical"
SEVERITY_HIGH = "High"
SEVERITY_MEDIUM = "Medium"
SEVERITY_LOW = "Low"
SEVERITY_INFORMATIONAL = "Informational"

LIKELIHOOD_HIGH = "High"
LIKELIHOOD_MEDIUM = "Medium"
LIKELIHOOD_LOW = "Low"

def compute_risk_level(severity: str, likelihood: str) -> str:
    """
    Computes qualitative risk level from Impact (Severity) and Likelihood.
    Standard NIST / OWASP Risk Rating Matrix.
    """
    if severity == SEVERITY_INFORMATIONAL:
        return SEVERITY_INFORMATIONAL

    matrix = {
        (SEVERITY_CRITICAL, LIKELIHOOD_HIGH): SEVERITY_CRITICAL,
        (SEVERITY_CRITICAL, LIKELIHOOD_MEDIUM): SEVERITY_CRITICAL,
        (SEVERITY_CRITICAL, LIKELIHOOD_LOW): SEVERITY_HIGH,
        (SEVERITY_HIGH, LIKELIHOOD_HIGH): SEVERITY_HIGH,
        (SEVERITY_HIGH, LIKELIHOOD_MEDIUM): SEVERITY_HIGH,
        (SEVERITY_HIGH, LIKELIHOOD_LOW): SEVERITY_MEDIUM,
        (SEVERITY_MEDIUM, LIKELIHOOD_HIGH): SEVERITY_MEDIUM,
        (SEVERITY_MEDIUM, LIKELIHOOD_MEDIUM): SEVERITY_MEDIUM,
        (SEVERITY_MEDIUM, LIKELIHOOD_LOW): SEVERITY_LOW,
        (SEVERITY_LOW, LIKELIHOOD_HIGH): SEVERITY_LOW,
        (SEVERITY_LOW, LIKELIHOOD_MEDIUM): SEVERITY_LOW,
        (SEVERITY_LOW, LIKELIHOOD_LOW): SEVERITY_LOW,
    }
    return matrix.get((severity, likelihood), severity)

# ---------------------------------------------------------------------------
# Network Probing & Client Abstraction
# ---------------------------------------------------------------------------
def is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a local port is actively accepting TCP connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0

class UnifiedResponse:
    """Normalized response representation across HTTP and TestClient."""
    def __init__(self, status_code: int, headers: Dict[str, str], text: str):
        self.status_code = status_code
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.text = text

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except Exception:
            return None

class UnifiedClient:
    """Wrapper that sends requests either via HTTPX (live) or TestClient (in-process)."""
    def __init__(self, mode: str, base_url: str, underlying_client: Any):
        self.mode = mode  # 'live' or 'in-process'
        self.base_url = base_url
        self.client = underlying_client

    def get(self, path: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> UnifiedResponse:
        try:
            r = self.client.get(path, headers=headers or {}, params=params)
            return UnifiedResponse(r.status_code, dict(r.headers), r.text)
        except Exception as exc:
            return UnifiedResponse(599, {}, json.dumps({"error": f"Client request error: {str(exc)}"}))

    def post(self, path: str, json: Optional[Any] = None, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> UnifiedResponse:
        try:
            r = self.client.post(path, json=json, headers=headers or {}, params=params)
            return UnifiedResponse(r.status_code, dict(r.headers), r.text)
        except Exception as exc:
            return UnifiedResponse(599, {}, json.dumps({"error": f"Client request error: {str(exc)}"}))

    def delete(self, path: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> UnifiedResponse:
        try:
            r = self.client.delete(path, headers=headers or {}, params=params)
            return UnifiedResponse(r.status_code, dict(r.headers), r.text)
        except Exception as exc:
            return UnifiedResponse(599, {}, json.dumps({"error": f"Client request error: {str(exc)}"}))

# Lazy loaded app singletons
_hub_test_client = None
_booking_test_client = None
_passenger_test_client = None

def get_client(service_name: str) -> Optional[UnifiedClient]:
    """
    Factory creating a UnifiedClient for the requested agent:
    - Checks live HTTP port first.
    - If inactive, falls back to in-process FastAPI TestClient where possible.
    - Returns None if service cannot be contacted or instantiated.
    """
    import httpx

    global _hub_test_client, _booking_test_client, _passenger_test_client

    if service_name == "hub":
        if is_port_listening(PORT_HUB):
            return UnifiedClient("live", HUB_BASE_URL, httpx.Client(base_url=HUB_BASE_URL, timeout=10.0))
        if _hub_test_client is None:
            try:
                import importlib.util
                hub_dir = os.path.join(PROJECT_ROOT, "M3-Comunication-Hub&Booking-Agent", "agent-hub")
                m3_root = os.path.join(PROJECT_ROOT, "M3-Comunication-Hub&Booking-Agent")
                for p in (m3_root, hub_dir):
                    if p not in sys.path:
                        sys.path.insert(0, p)
                hub_main = os.path.join(hub_dir, "main.py")
                spec = importlib.util.spec_from_file_location("hub_main_assessment", hub_main)
                hub_mod = importlib.util.module_from_spec(spec)
                sys.modules["hub_main_assessment"] = hub_mod
                spec.loader.exec_module(hub_mod)
                from fastapi.testclient import TestClient
                _hub_test_client = TestClient(hub_mod.app, raise_server_exceptions=False)
            except Exception as e:
                print(f"[config] Hub TestClient fallback failed: {e}")
                return None
        return UnifiedClient("in-process", HUB_BASE_URL, _hub_test_client)

    elif service_name == "booking":
        if is_port_listening(PORT_BOOKING):
            return UnifiedClient("live", BOOKING_BASE_URL, httpx.Client(base_url=BOOKING_BASE_URL, timeout=10.0))
        if _booking_test_client is None:
            try:
                import importlib.util
                booking_dir = os.path.join(PROJECT_ROOT, "M3-Comunication-Hub&Booking-Agent", "booking-agent")
                m3_root = os.path.join(PROJECT_ROOT, "M3-Comunication-Hub&Booking-Agent")
                for p in (m3_root, booking_dir):
                    if p not in sys.path:
                        sys.path.insert(0, p)
                booking_main = os.path.join(booking_dir, "main.py")
                spec = importlib.util.spec_from_file_location("booking_main_assessment", booking_main)
                booking_mod = importlib.util.module_from_spec(spec)
                sys.modules["booking_main_assessment"] = booking_mod
                spec.loader.exec_module(booking_mod)
                from fastapi.testclient import TestClient
                _booking_test_client = TestClient(booking_mod.app, raise_server_exceptions=False)
            except Exception as e:
                print(f"[config] Booking TestClient fallback failed: {e}")
                return None
        return UnifiedClient("in-process", BOOKING_BASE_URL, _booking_test_client)

    elif service_name == "passenger":
        if is_port_listening(PORT_PASSENGER):
            return UnifiedClient("live", PASSENGER_BASE_URL, httpx.Client(base_url=PASSENGER_BASE_URL, timeout=10.0))
        # Note: Passenger Assistant relies heavily on sentence-transformers and Supabase.
        # If live port is not active, tests needing passenger agent will report INCONCLUSIVE.
        return None

    elif service_name == "ops":
        if is_port_listening(PORT_OPS):
            return UnifiedClient("live", OPS_BASE_URL, httpx.Client(base_url=OPS_BASE_URL, timeout=10.0))
        return None

    elif service_name == "maintenance":
        if is_port_listening(PORT_MAINTENANCE):
            return UnifiedClient("live", MAINTENANCE_BASE_URL, httpx.Client(base_url=MAINTENANCE_BASE_URL, timeout=10.0))
        return None

    return None

# ---------------------------------------------------------------------------
# JWT Helper for M3 Assessment Testing
# ---------------------------------------------------------------------------
def generate_assessment_token(
    sub: str = "passenger-agent",
    exp_delta_seconds: int = 3600,
    secret: Optional[str] = None,
    algorithm: str = "HS256",
    user_id: Optional[str] = None,
) -> str:
    """Generate a valid or intentionally forged JWT for authentication testing."""
    import jwt

    m3_root = os.path.join(PROJECT_ROOT, "M3-Comunication-Hub&Booking-Agent")
    agent_hub = os.path.join(m3_root, "agent-hub")
    for p in (m3_root, agent_hub):
        if p not in sys.path:
            sys.path.insert(0, p)

    try:
        from auth.jwt_utils import get_jwt_secret, get_jwt_algorithm
        target_secret = secret if secret is not None else get_jwt_secret()
        target_alg = algorithm if algorithm is not None else get_jwt_algorithm()
    except Exception:
        target_secret = secret or os.getenv("JWT_SECRET_KEY", "change-me")
        target_alg = algorithm or "HS256"

    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": sub,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=exp_delta_seconds)).timestamp()),
        "iss": "railsense-hub",
        "aud": "railsense-services",
    }
    if user_id:
        payload["user_id"] = user_id

    return jwt.encode(payload, target_secret, algorithm=target_alg)
