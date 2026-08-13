"""
main.py — RailSense Hub · Security Agent (M3)
FastAPI application — all routes across Phases 1–5.

Phase 1 delivered:
  GET  /health              — liveness check
  POST /hub/register        — agents declare name + base URL on startup
  POST /hub/send            — validates HubMessage, returns phase1-stub
  POST /auth/login          — dummy token
  POST /auth/verify         — always valid

Phase 2 activates:
  POST /auth/login          — real bcrypt credential check + HS256 JWT issue
  POST /auth/verify         — real signature + expiry + revocation check
  POST /auth/revoke         — add token to revocation blacklist
  POST /hub/send            — real JWT verification middleware; AES-256 payload
                              encryption on encrypt_payload=True messages
  POST /hub/register        — optional AGENT_REGISTRATION_SECRET enforcement

Phase 3 activates:
  POST /security/fraud-check — Isolation Forest anomaly detection on booking events

Later phases add to this file:
  Phase 4  — GET  /security/audit-log
             GET  /security/sessions
             POST /security/vulnerability-check
             rate-limiting middleware
  Phase 5  — hub_client integration, fraud_alert push events
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError

from audit_log import log_message
from auth.crypto import encrypt_payload as aes_encrypt
from auth.hashing import hash_secret, verify_secret
from auth.jwt_handler import decode_token, issue_token, revoke_token, verify_token
from auth.sanitize import run_vulnerability_check
from fraud.fraud_check import score_booking
from schema import AgentRegistration, BookingEvent, HubMessage, LoginRequest, RevokeRequest, VerifyRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RailSense Hub — Security Agent",
    description=(
        "Central Agent Communication Hub for the RailSense AI system (IT3041). "
        "Routes messages between Passenger, Operations, and Maintenance agents. "
        "Handles authentication, fraud detection, audit logging, and rate limiting "
        "across Phases 1–5."
    ),
    version="phase3-v0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — all agents call this Hub from different ports on localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Phase 5: tighten to specific agent origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory agent registry
# { agent_id: { "base_url": str, "port": int|None, "registered_at": str } }
# Phase 5: entries also track last_seen for online/offline detection.
# ---------------------------------------------------------------------------

_registry: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# In-memory agent credential store — Phase 2
#
# Pre-seeded with the four known RailSense agents.  Secrets are stored as
# bcrypt hashes — never plaintext.  The plaintext secrets are defined in
# .env.example for development; change them in production.
#
# Additional agents can be registered at runtime via POST /hub/register.
# ---------------------------------------------------------------------------

_AGENT_SECRETS: Dict[str, str] = {
    "passenger-agent":   hash_secret(os.getenv("PASSENGER_SECRET",   "passenger-dev-secret")),
    "operations-agent":  hash_secret(os.getenv("OPERATIONS_SECRET",  "operations-dev-secret")),
    "maintenance-agent": hash_secret(os.getenv("MAINTENANCE_SECRET",  "maintenance-dev-secret")),
    "security-agent":    hash_secret(os.getenv("SECURITY_SECRET",    "security-dev-secret")),
}

# Optional secret that locks POST /hub/register
_REGISTRATION_SECRET: Optional[str] = os.getenv("AGENT_REGISTRATION_SECRET", "")


# ---------------------------------------------------------------------------
# Root route & Health check
# ---------------------------------------------------------------------------


@app.get(
    "/",
    summary="Hub root endpoint",
    tags=["Hub"],
    include_in_schema=False,
)
def root():
    """Redirect root path to interactive Swagger API documentation."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")


@app.get(
    "/health",
    summary="Hub liveness check",
    tags=["Hub"],
    response_description="Service name, version, status, and currently registered agents.",
)
def health() -> Dict[str, Any]:
    """
    Returns the Hub service status and the list of currently registered agents.

    This endpoint is always available, even when auth or fraud detection is
    not yet active.  Other agents should poll this on startup to confirm
    the Hub is reachable before attempting to register or send messages.

    **Phase 2 response example:**
    ```json
    {
      "service": "railsense-hub",
      "version": "phase2-v0",
      "status": "ok",
      "auth": "jwt_hs256",
      "registered_agents": ["passenger-agent", "operations-agent"]
    }
    ```
    """
    return {
        "service": "railsense-hub",
        "version": "phase2-v0",
        "status": "ok",
        "auth": "jwt_hs256",
        "encryption": "aes256_fernet",
        "registered_agents": list(_registry.keys()),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Agent registration
# ---------------------------------------------------------------------------


@app.post(
    "/hub/register",
    summary="Register an agent with the Hub",
    tags=["Hub"],
    status_code=status.HTTP_201_CREATED,
)
def register_agent(
    registration: AgentRegistration,
    x_agent_secret: Optional[str] = Header(None, alias="X-Agent-Secret"),
) -> Dict[str, Any]:
    """
    Agents call this endpoint on startup to declare their name and base URL.

    The Hub uses the registered base URL to forward messages in `POST /hub/send`.
    Re-registering an existing agent ID updates its base URL.

    **Phase 2:** If the `AGENT_REGISTRATION_SECRET` environment variable is set,
    the `X-Agent-Secret` header must match it; otherwise registration is rejected
    with `403 Forbidden`.

    **Registration payload:**
    ```json
    {
      "agent_id": "passenger-agent",
      "base_url": "http://localhost:8002",
      "port": 8002
    }
    ```
    """
    # Optional registration secret enforcement (Phase 2)
    if _REGISTRATION_SECRET and x_agent_secret != _REGISTRATION_SECRET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "detail": (
                    "Registration rejected — X-Agent-Secret header is missing or incorrect. "
                    "Set AGENT_REGISTRATION_SECRET in the Hub .env to manage this."
                ),
                "status": "rejected",
            },
        )

    agent_id = registration.agent_id
    _registry[agent_id] = {
        "base_url": registration.base_url,
        "port": registration.port,
        "registered_at": datetime.utcnow().isoformat(),
    }
    logger.info("Agent '%s' registered at %s", agent_id, registration.base_url)
    return {
        "status": "registered",
        "agent_id": agent_id,
        "base_url": registration.base_url,
        "message": (
            f"Agent '{agent_id}' registered successfully. "
            "Obtain a JWT via POST /auth/login and include it in every /hub/send message."
        ),
    }


# ---------------------------------------------------------------------------
# Message routing — core Hub endpoint
# ---------------------------------------------------------------------------


@app.post(
    "/hub/send",
    summary="Route a message from one agent to another",
    tags=["Hub"],
)
def send_message(message: HubMessage) -> Dict[str, Any]:
    """
    Validates the message schema, verifies the JWT, checks sender registration,
    and forwards to the target agent's base URL.

    **Phase 2:** JWT signature and expiry are verified before any routing logic
    runs.  Invalid or expired tokens receive `401`.  Messages with
    `encrypt_payload: true` have their payload AES-256 encrypted before
    forwarding.

    **Valid request returns:**
    ```json
    {
      "message_id": "b7e1-uuid",
      "sender_agent": "passenger-agent",
      "receiver_agent": "operations-agent",
      "intent": "delay_check",
      "status": "forwarded",
      "auth_method": "jwt_hs256",
      "encrypted": false,
      "timestamp": "2026-09-10T13:58:12"
    }
    ```

    **Errors:**
    - `401 Unauthorized` — invalid or expired JWT.
    - `400 Bad Request`  — sender not registered.
    - `422 Unprocessable Entity` — schema or sanitization failure.
    """
    start_ts = time.monotonic()

    # ── Phase 2 JWT verification ────────────────────────────────────────────
    try:
        verify_token(message.auth_token)
    except JWTError as exc:
        log_message(
            message_id=message.message_id,
            sender=message.sender_agent,
            receiver=message.receiver_agent,
            intent=message.intent,
            status="rejected",
            timestamp=message.timestamp,
            extra={"rejection_reason": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "detail": f"Token verification failed: {exc}",
                "status": "rejected",
                "message_id": message.message_id,
            },
        ) from exc

    # ── Sender registration check ───────────────────────────────────────────
    if message.sender_agent not in _registry:
        log_message(
            message_id=message.message_id,
            sender=message.sender_agent,
            receiver=message.receiver_agent,
            intent=message.intent,
            status="rejected",
            timestamp=message.timestamp,
            extra={"reason": "sender_not_registered"},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "detail": (
                    f"Sender '{message.sender_agent}' is not registered. "
                    "Call POST /hub/register before sending messages."
                ),
                "status": "rejected",
                "message_id": message.message_id,
            },
        )

    # ── Optional AES-256 payload encryption ─────────────────────────────────
    encrypted = False
    forwarded_payload = message.payload

    if message.encrypt_payload and message.payload:
        forwarded_payload = {"encrypted_data": aes_encrypt(message.payload)}
        encrypted = True
        logger.info(
            "Payload encrypted for message '%s' (intent: %s)",
            message.message_id, message.intent,
        )

    latency_ms = int((time.monotonic() - start_ts) * 1000)

    # ── Audit log ───────────────────────────────────────────────────────────
    log_message(
        message_id=message.message_id,
        sender=message.sender_agent,
        receiver=message.receiver_agent,
        intent=message.intent,
        status="forwarded",
        timestamp=message.timestamp,
        encrypted=encrypted,
        latency_ms=latency_ms,
    )

    logger.info(
        "Message '%s' forwarded: %s → %s [%s] latency=%dms encrypted=%s",
        message.message_id,
        message.sender_agent,
        message.receiver_agent,
        message.intent,
        latency_ms,
        encrypted,
    )

    # ── Response ────────────────────────────────────────────────────────────
    # Phase 2: real httpx forwarding to _registry[receiver_agent]["base_url"]
    # is added in Phase 5 when all agents are running.  Until then, the Hub
    # validates, logs, encrypts, and returns a confirmed "forwarded" response.
    return {
        "message_id": message.message_id,
        "sender_agent": message.sender_agent,
        "receiver_agent": message.receiver_agent,
        "intent": message.intent,
        "status": "forwarded",
        "auth_method": "jwt_hs256",
        "encrypted": encrypted,
        "latency_ms": latency_ms,
        "timestamp": message.timestamp.isoformat(),
    }


# ---------------------------------------------------------------------------
# Auth endpoints (Phase 2 — real implementations)
# ---------------------------------------------------------------------------


@app.post(
    "/auth/login",
    summary="Obtain an authentication token",
    tags=["Auth"],
)
def auth_login(credentials: LoginRequest) -> Dict[str, Any]:
    """
    Agents call this on startup to obtain a signed JWT for embedding in
    every subsequent Hub message as `auth_token`.

    **Phase 2:** Validates the agent secret against the stored bcrypt hash.
    Returns a signed HS256 JWT with configurable expiry.
    Returns `401` if the agent ID is unknown or the secret is incorrect.

    **Response:**
    ```json
    {
      "agent_id": "passenger-agent",
      "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
      "token_type": "bearer",
      "expires_in": 3600
    }
    ```
    """
    stored_hash = _AGENT_SECRETS.get(credentials.agent_id)
    if stored_hash is None or not verify_secret(credentials.secret, stored_hash):
        logger.warning("Login failed for agent '%s'", credentials.agent_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "detail": "Invalid agent_id or secret.",
                "status": "rejected",
            },
        )

    token = issue_token(credentials.agent_id, credentials.secret)
    expiry_minutes = int(os.getenv("JWT_EXPIRY_MINUTES", "60"))
    logger.info("Login successful for agent '%s'", credentials.agent_id)

    return {
        "agent_id": credentials.agent_id,
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expiry_minutes * 60,
    }


@app.post(
    "/auth/verify",
    summary="Verify an authentication token",
    tags=["Auth"],
)
def auth_verify(body: VerifyRequest) -> Dict[str, Any]:
    """
    Check whether a token is currently valid.

    **Phase 2:** Verifies the HS256 signature, expiry, and revocation list.
    Returns `{"valid": false, "reason": "..."}` for invalid / expired tokens.

    **Response (valid token):**
    ```json
    {
      "valid": true,
      "agent_id": "passenger-agent"
    }
    ```

    **Response (invalid token):**
    ```json
    {
      "valid": false,
      "reason": "Signature verification failed."
    }
    ```
    """
    try:
        verify_token(body.token)
        claims = decode_token(body.token) or {}
        return {
            "valid": True,
            "agent_id": claims.get("sub"),
        }
    except JWTError as exc:
        return {
            "valid": False,
            "reason": str(exc),
        }


@app.post(
    "/auth/revoke",
    summary="Revoke an authentication token",
    tags=["Auth"],
)
def auth_revoke(body: RevokeRequest) -> Dict[str, Any]:
    """
    Immediately invalidate a token.

    After revocation, any `POST /hub/send` call using the revoked token will
    receive a `401 Unauthorized` response even if the token has not expired.

    The revocation list is in-memory and is cleared on Hub restart.

    **Response:**
    ```json
    {
      "status": "revoked",
      "token_prefix": "eyJhbGciOiJIUzI1NiIs..."
    }
    ```
    """
    # Decode first so we can log the agent_id
    claims = decode_token(body.token) or {}
    agent_id = claims.get("sub", "unknown")

    revoke_token(body.token)
    logger.info("Token revoked for agent '%s'", agent_id)

    return {
        "status": "revoked",
        "agent_id": agent_id,
        "token_prefix": body.token[:32] + "...",
    }


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Phase 3 — POST /security/fraud-check
# ---------------------------------------------------------------------------


@app.post(
    "/security/fraud-check",
    summary="Score a booking event for fraud risk",
    tags=["Security"],
)
def fraud_check(event: BookingEvent) -> Dict[str, Any]:
    """
    Score a booking event using the Isolation Forest anomaly detection model.

    Called by the Passenger Agent before confirming a ticket. Returns a risk
    level (LOW / MEDIUM / HIGH), an anomaly score, the top contributing features,
    and a plain-English reason for the flag.

    Requires a valid JWT in the `auth_token` field.

    **High-risk booking example:**
    ```json
    {
      "user_id": "usr_4421",
      "event_id": "evt_9921",
      "anomaly_score": -0.41,
      "risk_level": "HIGH",
      "top_features": {"bookings_last_60s": 5, "time_since_last_booking": 4},
      "reason": "5 bookings detected within 60 seconds — pattern matches rapid automated purchasing.",
      "model_version": "phase3-iforest-v1",
      "threshold": -0.15
    }
    ```

    If `fraud_model.pkl` has not been trained yet, the endpoint falls back to
    a rule-based heuristic so the service is always demoable.
    """
    # ── JWT verification ────────────────────────────────────────────────────
    try:
        verify_token(event.auth_token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "detail": f"Token verification failed: {exc}",
                "status": "rejected",
            },
        ) from exc

    # ── Score the event ─────────────────────────────────────────────────────
    event_dict = event.dict(exclude={"auth_token"})
    result = score_booking(event_dict)

    # ── Audit log — flag HIGH risk events ────────────────────────────────────
    risk_flag = result["risk_level"] == "HIGH"
    log_message(
        message_id=event.event_id,
        sender="fraud-check",
        receiver="security-agent",
        intent="fraud_check",
        status=result["risk_level"].lower(),
        risk_flag=risk_flag,
    )

    if risk_flag:
        logger.warning(
            "HIGH risk booking flagged: user=%s event=%s score=%.4f reason=%s",
            event.user_id, event.event_id,
            result["anomaly_score"], result["reason"],
        )

    return result


# ---------------------------------------------------------------------------
# Phase 4 placeholders
# GET  /security/audit-log
# GET  /security/sessions
# POST /security/vulnerability-check
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Entry point (for running directly with `python main.py`)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
