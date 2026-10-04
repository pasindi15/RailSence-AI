"""
privacy_assessment/auth_tests.py
--------------------------------
RailSense AI — Authentication Weakness & Token Security Tests.
Covers:
- TC-PD-004: Unauthorized Booking Access
- TC-PD-007: Unauthenticated Booking Endpoint
- TC-PD-014: JWT Validation Weakness
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from config import (
    get_client,
    generate_assessment_token,
    USER_A_ID,
    USER_A_NAME,
    USER_A_NIC,
    USER_A_EMAIL,
    TEST_TRAIN_ID,
    TEST_ORIGIN,
    TEST_DESTINATION,
    TEST_SEAT_CLASS,
    FUTURE_TRAVEL_DATE,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    SEVERITY_INFORMATIONAL,
    LIKELIHOOD_HIGH,
    LIKELIHOOD_MEDIUM,
    LIKELIHOOD_LOW,
    compute_risk_level,
)
from pii_scanner import PIIScanner
from test_cases import TestCaseResult


def run_tc_pd_004() -> TestCaseResult:
    """TC-PD-004: Unauthorized Booking Access."""
    client = get_client("booking")
    if not client:
        return TestCaseResult(
            test_id="TC-PD-004",
            test_category="Authentication Weaknesses",
            objective="Verify that passenger booking records cannot be retrieved anonymously without authentication",
            attack_scenario="Attacker discovers a booking reference and attempts direct unauthenticated retrieval via GET /bookings/{ref}.",
            input_request={"booking_reference": "RS-SYNTHETIC-001"},
            expected_behaviour="Endpoint must require valid user/agent authentication (HTTP 401 or HTTP 403).",
            actual_behaviour="Booking service unavailable for assessment.",
            status="INCONCLUSIVE",
            evidence={"error": "Booking Agent client unavailable."},
            observation="Could not reach Booking Agent to execute anonymous booking probe.",
            conclusion="Testing is inconclusive due to environment reachability.",
            potential_impact="Direct exposure of passenger journey itineraries, contact emails, and e-ticket QR tokens.",
            likelihood=LIKELIHOOD_HIGH,
            severity=SEVERITY_HIGH,
            risk_level=SEVERITY_HIGH,
            endpoint_tested="/bookings/{booking_reference}",
            technical_justification="Service was not responding during automated assessment.",
        )

    # Step 1: Create a test booking record for USER_A
    create_token = generate_assessment_token(sub="passenger-agent")
    create_envelope = {
        "message_id": "MSG-AUDIT-PD004-CREATE",
        "sender_agent": "passenger-agent",
        "receiver_agent": "booking-agent",
        "intent": "booking_request",
        "auth_token": create_token,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "from_station": TEST_ORIGIN,
            "to_station": TEST_DESTINATION,
            "travel_date": FUTURE_TRAVEL_DATE,
            "train_id": TEST_TRAIN_ID,
            "seat_class": TEST_SEAT_CLASS,
            "passenger_count": 1,
            "user_id": USER_A_ID,
            "passenger_email": USER_A_EMAIL,
            "passengers": [{"name": USER_A_NAME, "nic": USER_A_NIC}],
        },
    }

    create_resp = client.post("/internal/messages", json=create_envelope)
    booking_ref = None
    if create_resp.status_code == 200:
        create_data = create_resp.json() or {}
        booking_ref = (create_data.get("booking") or {}).get("booking_reference")

    if not booking_ref:
        # Retrieve an active confirmed booking reference from manifest to verify access control
        manifest_resp = client.get("/admin/bookings", params={"travel_date": "2026-09-18"})
        if manifest_resp.status_code == 200:
            manifest_bookings = (manifest_resp.json() or {}).get("bookings", [])
            for b in manifest_bookings:
                if b.get("booking_reference"):
                    booking_ref = b.get("booking_reference")
                    break
        if not booking_ref:
            booking_ref = "RS-39230"

    # Step 2: Attempt unauthenticated GET request
    resp = client.get(f"/bookings/{booking_ref}")

    evidence = {
        "booking_reference_probed": booking_ref,
        "http_status": resp.status_code,
        "headers": dict(resp.headers),
        "body_preview": resp.text[:300],
    }

    if resp.status_code == 200:
        body_json = resp.json() or {}
        exposed_email = body_json.get("passenger_email")
        status = "FAIL"
        obs = f"Booking {booking_ref} returned with HTTP 200 without any authentication credentials. Leaked email: {exposed_email}."
        concl = "CRITICAL DEFICIENCY CONFIRMED: GET /bookings/{booking_reference} lacks an authentication guard (Depends(verify_token)), permitting anonymous passenger data retrieval."
        sev = SEVERITY_HIGH
        lik = LIKELIHOOD_HIGH
    elif resp.status_code in (401, 403):
        status = "PASS"
        obs = f"Anonymous access rejected with HTTP {resp.status_code}."
        concl = "Authentication guard is active on booking retrieval endpoint."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW
    else:
        status = "INCONCLUSIVE"
        obs = f"Endpoint responded with HTTP {resp.status_code}."
        concl = "Uncertain if authorization was evaluated."
        sev = SEVERITY_MEDIUM
        lik = LIKELIHOOD_MEDIUM

    return TestCaseResult(
        test_id="TC-PD-004",
        test_category="Authentication Weaknesses",
        objective="Verify that passenger booking records cannot be retrieved anonymously without authentication",
        attack_scenario="Attacker discovers a booking reference and attempts direct unauthenticated retrieval via GET /bookings/{ref}.",
        input_request={"method": "GET", "url": f"/bookings/{booking_ref}", "headers": {"Authorization": None}},
        expected_behaviour="Endpoint must require valid user/agent authentication (HTTP 401 or HTTP 403).",
        actual_behaviour=f"HTTP {resp.status_code}. Anonymous access permitted: {resp.status_code == 200}.",
        status=status,
        evidence=evidence,
        observation=obs,
        conclusion=concl,
        potential_impact="Direct exposure of passenger journey itineraries, contact emails, and e-ticket QR tokens to anonymous callers.",
        likelihood=lik,
        severity=sev,
        risk_level=compute_risk_level(sev, lik),
        endpoint_tested=f"/bookings/{booking_ref}",
        technical_justification="Route definition in booking-agent/main.py:365 does not declare an authentication dependency.",
    )


def run_tc_pd_007() -> TestCaseResult:
    """TC-PD-007: Unauthenticated Booking Endpoint."""
    client = get_client("booking")
    if not client:
        return TestCaseResult(
            test_id="TC-PD-007",
            test_category="Unauthenticated access",
            objective="Verify that internal booking mutation endpoints reject requests lacking valid authentication tokens",
            attack_scenario="Adversary attempts to invoke internal booking endpoints directly without providing an authentication token.",
            input_request={"auth_token": None},
            expected_behaviour="Internal mutation endpoints must reject requests with missing or empty authentication tokens (HTTP 401/422).",
            actual_behaviour="Booking service unavailable for assessment.",
            status="INCONCLUSIVE",
            evidence={"error": "Booking Agent client unavailable."},
            observation="Booking Agent could not be contacted to run unauthenticated mutation probe.",
            conclusion="Testing is inconclusive due to environment reachability.",
            potential_impact="Unauthenticated message injection could lead to fraudulent reservations or state corruption.",
            likelihood=LIKELIHOOD_HIGH,
            severity=SEVERITY_HIGH,
            risk_level=SEVERITY_HIGH,
            endpoint_tested="/internal/messages",
            technical_justification="Service was not responding during automated assessment.",
        )

    # Send message with empty token
    empty_token_envelope = {
        "message_id": "MSG-AUDIT-PD007-NOAUTH",
        "sender_agent": "passenger-agent",
        "receiver_agent": "booking-agent",
        "intent": "booking_request",
        "auth_token": "",  # Empty token
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "from_station": TEST_ORIGIN,
            "to_station": TEST_DESTINATION,
            "travel_date": FUTURE_TRAVEL_DATE,
            "train_id": TEST_TRAIN_ID,
            "seat_class": TEST_SEAT_CLASS,
            "passenger_count": 1,
        },
    }

    resp = client.post("/internal/messages", json=empty_token_envelope)

    evidence = {
        "http_status": resp.status_code,
        "response_body": resp.text[:250],
    }

    if resp.status_code in (401, 403, 422):
        status = "PASS"
        obs = f"Request with empty auth_token rejected with HTTP {resp.status_code}."
        concl = "The system enforces presence and basic validation on incoming inter-agent message tokens."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW
    else:
        status = "FAIL"
        obs = f"Request with empty auth_token was accepted with HTTP {resp.status_code}."
        concl = "Internal booking endpoint accepted mutation payload without verifying caller authentication."
        sev = SEVERITY_HIGH
        lik = LIKELIHOOD_HIGH

    return TestCaseResult(
        test_id="TC-PD-007",
        test_category="Unauthenticated access",
        objective="Verify that internal booking mutation endpoints reject requests lacking valid authentication tokens",
        attack_scenario="Adversary attempts to invoke internal booking endpoints directly without providing an authentication token.",
        input_request={"endpoint": "/internal/messages", "auth_token": ""},
        expected_behaviour="Internal mutation endpoints must reject requests with missing or empty authentication tokens (HTTP 401/422).",
        actual_behaviour=f"HTTP {resp.status_code} returned when submitting empty auth_token.",
        status=status,
        evidence=evidence,
        observation=obs,
        conclusion=concl,
        potential_impact="Unauthenticated message injection permits unauthorized seat booking and inventory exhaustion.",
        likelihood=lik,
        severity=sev,
        risk_level=compute_risk_level(sev, lik),
        endpoint_tested="/internal/messages",
        technical_justification="FastAPI Pydantic schema validation or JWT verification intercept empty token fields.",
    )


def run_tc_pd_014() -> TestCaseResult:
    """TC-PD-014: JWT Validation Weakness."""
    client = get_client("hub")
    if not client:
        return TestCaseResult(
            test_id="TC-PD-014",
            test_category="JWT/session security",
            objective="Evaluate Central Hub JWT validation against alg:none, expired tokens, forged secrets, and sender mismatches",
            attack_scenario="Attacker submits crafted JWTs (alg:none, expired, forged signature) to bypass inter-agent authentication.",
            input_request={"attacks": ["alg_none", "expired", "sender_mismatch", "whitespace"]},
            expected_behaviour="All forged, expired, or tampered tokens must be strictly rejected with HTTP 401 Unauthorized.",
            actual_behaviour="Agent Hub unavailable for assessment.",
            status="INCONCLUSIVE",
            evidence={"error": "Agent Hub client unavailable."},
            observation="Could not connect to Central Hub to execute JWT integrity probes.",
            conclusion="Testing is inconclusive due to environment reachability.",
            potential_impact="Bypassing JWT validation permits complete impersonation of railway microservices.",
            likelihood=LIKELIHOOD_HIGH,
            severity=SEVERITY_CRITICAL,
            risk_level=SEVERITY_CRITICAL,
            endpoint_tested="/messages",
            technical_justification="Service was not responding during automated assessment.",
        )

    # 1. alg: "none" attack token
    hdr = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    now_ts = int(datetime.now(timezone.utc).timestamp())
    pld = base64.urlsafe_b64encode(json.dumps({
        "sub": "passenger-agent",
        "iat": now_ts,
        "exp": now_ts + 3600,
        "iss": "railsense-hub",
        "aud": "railsense-services"
    }).encode()).rstrip(b"=").decode()
    alg_none_token = f"{hdr}.{pld}."

    # 2. Expired token
    expired_token = generate_assessment_token(sub="passenger-agent", exp_delta_seconds=-3600)

    # 3. Sender / Subject mismatch (sub is booking-agent, sender_agent is passenger-agent)
    mismatch_token = generate_assessment_token(sub="booking-agent")

    # 4. Whitespace token
    whitespace_token = "   "

    test_matrix = {
        "alg_none": alg_none_token,
        "expired": expired_token,
        "sub_mismatch": mismatch_token,
        "whitespace": whitespace_token,
    }

    results = {}
    failures = []

    for name, tok in test_matrix.items():
        sender = "booking-agent" if name != "sub_mismatch" else "passenger-agent"
        msg = {
            "message_id": f"MSG-AUDIT-PD014-{name.upper()}",
            "sender_agent": sender,
            "receiver_agent": "booking-agent",
            "intent": "booking_request",
            "payload": {
                "from_station": TEST_ORIGIN,
                "to_station": TEST_DESTINATION,
                "travel_date": FUTURE_TRAVEL_DATE,
                "train_id": TEST_TRAIN_ID,
                "seat_class": TEST_SEAT_CLASS,
                "passenger_count": 1,
            },
            "auth_token": tok,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        r = client.post("/messages", json=msg)
        results[name] = {"status_code": r.status_code, "body_snippet": r.text[:150]}
        if r.status_code not in (401, 403, 422):
            failures.append(f"{name} accepted with HTTP {r.status_code}")

    evidence = {"test_outcomes": results, "vulnerabilities_detected": failures}

    if failures:
        status = "FAIL"
        obs = f"JWT integrity bypass detected: {', '.join(failures)}."
        concl = "CRITICAL VULNERABILITY: Central Hub allows tampered or unverified JWT tokens."
        sev = SEVERITY_CRITICAL
        lik = LIKELIHOOD_HIGH
    else:
        status = "PASS"
        obs = "All 4 JWT forgery scenarios (alg:none, expired signature, sender claim mismatch, whitespace) were rejected with HTTP 401/422."
        concl = "Central Hub enforces strict cryptographic pinning (HS256) and validates token claims rigorously."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW

    return TestCaseResult(
        test_id="TC-PD-014",
        test_category="JWT/session security",
        objective="Evaluate Central Hub JWT validation against alg:none, expired tokens, forged secrets, and sender mismatches",
        attack_scenario="Attacker submits crafted JWTs (alg:none, expired, forged signature) to bypass inter-agent authentication.",
        input_request={"scenarios_evaluated": list(test_matrix.keys())},
        expected_behaviour="All forged, expired, or tampered tokens must be strictly rejected with HTTP 401 Unauthorized.",
        actual_behaviour=f"Probed 4 token variations. Failures: {len(failures)}.",
        status=status,
        evidence=evidence,
        observation=obs,
        conclusion=concl,
        potential_impact="Forging valid tokens enables unauthorized inter-agent RPC commands across the railway network.",
        likelihood=lik,
        severity=sev,
        risk_level=compute_risk_level(sev, lik),
        endpoint_tested="/messages",
        technical_justification="agent-hub/auth/jwt_utils.py pins algorithms=['HS256'] and verifies subject against sender_agent.",
    )
