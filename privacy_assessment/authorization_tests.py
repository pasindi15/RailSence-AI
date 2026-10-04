"""
privacy_assessment/authorization_tests.py
-----------------------------------------
RailSense AI — Authorization, IDOR & Access Control Security Tests.
Covers:
- TC-PD-005: IDOR Using User ID
- TC-PD-006: IDOR Using Booking Reference
- TC-PD-008: Unauthenticated Cancellation Endpoint
- TC-PD-009: Unauthorized Admin Endpoint Access
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Any

from config import (
    get_client,
    generate_assessment_token,
    USER_A_ID,
    USER_A_NAME,
    USER_A_NIC,
    USER_A_EMAIL,
    USER_B_ID,
    USER_B_NAME,
    USER_B_NIC,
    USER_B_EMAIL,
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


def _create_booking_for_user(user_id: str, email: str, name: str, nic: str, client) -> str | None:
    """Helper to create a dedicated synthetic test booking record."""
    token = generate_assessment_token(sub="passenger-agent")
    envelope = {
        "message_id": f"MSG-AUDIT-IDOR-{user_id[:8]}",
        "sender_agent": "passenger-agent",
        "receiver_agent": "booking-agent",
        "intent": "booking_request",
        "auth_token": token,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "from_station": TEST_ORIGIN,
            "to_station": TEST_DESTINATION,
            "travel_date": FUTURE_TRAVEL_DATE,
            "train_id": TEST_TRAIN_ID,
            "seat_class": TEST_SEAT_CLASS,
            "passenger_count": 1,
            "user_id": user_id,
            "passenger_email": email,
            "passengers": [{"name": name, "nic": nic}],
        },
    }
    r = client.post("/internal/messages", json=envelope)
    if r.status_code == 200:
        data = r.json() or {}
        return (data.get("booking") or {}).get("booking_reference")
    return None


def run_tc_pd_005() -> TestCaseResult:
    """TC-PD-005: IDOR Using User ID."""
    client = get_client("booking")
    if not client:
        return TestCaseResult(
            test_id="TC-PD-005",
            test_category="Authorization / IDOR",
            objective="Verify whether an attacker (USER_B) can read a victim's (USER_A) booking by providing user_id parameter",
            attack_scenario="Attacker (USER_B) learns USER_A's booking reference and calls GET /bookings/{ref}?user_id=USER_B.",
            input_request={"user_id_param": USER_B_ID},
            expected_behaviour="The system must deny access with HTTP 403 Forbidden when user_id does not match the booking owner.",
            actual_behaviour="Booking service unavailable for assessment.",
            status="INCONCLUSIVE",
            evidence={"error": "Booking Agent client unavailable."},
            observation="Could not reach Booking Agent to execute cross-user IDOR probe.",
            conclusion="Testing is inconclusive due to environment reachability.",
            potential_impact="Insecure Direct Object Reference allows cross-user data exfiltration.",
            likelihood=LIKELIHOOD_HIGH,
            severity=SEVERITY_HIGH,
            risk_level=SEVERITY_HIGH,
            endpoint_tested="/bookings/{booking_reference}?user_id={id}",
            technical_justification="Service was not responding during automated assessment.",
        )

    # Step 1: Create booking as USER_A or retrieve an existing confirmed user booking
    ref_a = _create_booking_for_user(USER_A_ID, USER_A_EMAIL, USER_A_NAME, USER_A_NIC, client)
    if not ref_a:
        # Fallback to confirmed user booking reference from database
        ref_a = "RS-39230"

    # Step 2: Attempt retrieval supplying USER_B identity
    resp = client.get(f"/bookings/{ref_a}", params={"user_id": USER_B_ID})

    evidence = {
        "victim_booking_ref": ref_a,
        "victim_user_id": USER_A_ID,
        "attacker_user_id": USER_B_ID,
        "http_status": resp.status_code,
        "response_body_redacted": PIIScanner.redact_text(resp.text[:300]),
    }

    if resp.status_code == 200:
        # Cross-user access succeeded
        status = "FAIL"
        obs = f"USER_B successfully retrieved USER_A's booking {ref_a} using user_id={USER_B_ID}. Response returned HTTP 200."
        concl = "CRITICAL IDOR VULNERABILITY CONFIRMED: Ownership validation in GET /bookings/{ref} fails when user_id is passed for another user."
        sev = SEVERITY_HIGH
        lik = LIKELIHOOD_HIGH
    elif resp.status_code == 403:
        status = "PASS"
        obs = f"Cross-user access denied with HTTP 403 Forbidden. Ownership validation is functioning when user_id parameter is present."
        concl = "Direct parameter modification is successfully blocked by the authorization check."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW
    else:
        status = "INCONCLUSIVE"
        obs = f"Endpoint responded with HTTP {resp.status_code}."
        concl = "Access control behavior could not be definitively asserted."
        sev = SEVERITY_MEDIUM
        lik = LIKELIHOOD_MEDIUM

    return TestCaseResult(
        test_id="TC-PD-005",
        test_category="Authorization / IDOR",
        objective="Verify whether an attacker (USER_B) can read a victim's (USER_A) booking by providing user_id parameter",
        attack_scenario="Attacker (USER_B) learns USER_A's booking reference and calls GET /bookings/{ref}?user_id=USER_B.",
        input_request={"endpoint": f"/bookings/{ref_a}", "query_param": {"user_id": USER_B_ID}},
        expected_behaviour="The system must deny access with HTTP 403 Forbidden when user_id does not match the booking owner.",
        actual_behaviour=f"HTTP {resp.status_code}. Cross-user access permitted: {resp.status_code == 200}.",
        status=status,
        evidence=evidence,
        observation=obs,
        conclusion=concl,
        potential_impact="Breaches passenger confidentiality and exposes personal travel itineraries to unauthorized users.",
        likelihood=lik,
        severity=sev,
        risk_level=compute_risk_level(sev, lik),
        endpoint_tested=f"/bookings/{ref_a}?user_id={USER_B_ID}",
        technical_justification="Evaluated against booking-agent/main.py:391 authorization guard.",
    )


def run_tc_pd_006() -> TestCaseResult:
    """TC-PD-006: IDOR Using Booking Reference (Parameter Omission Bypass)."""
    client = get_client("booking")
    if not client:
        return TestCaseResult(
            test_id="TC-PD-006",
            test_category="Authorization / IDOR",
            objective="Verify whether omitting user_id query parameter completely bypasses booking ownership enforcement",
            attack_scenario="Attacker discovers victim's booking reference and requests GET /bookings/{ref} with no user_id parameter.",
            input_request={"booking_reference": "RS-PROBE-006"},
            expected_behaviour="Endpoint must require caller authentication and reject unverified requests (HTTP 401/403).",
            actual_behaviour="Booking service unavailable for assessment.",
            status="INCONCLUSIVE",
            evidence={"error": "Booking Agent client unavailable."},
            observation="Booking Agent could not be contacted to run IDOR parameter omission probe.",
            conclusion="Testing is inconclusive due to environment reachability.",
            potential_impact="Complete bypass of passenger identity validation allows enumeration of bookings.",
            likelihood=LIKELIHOOD_HIGH,
            severity=SEVERITY_HIGH,
            risk_level=SEVERITY_HIGH,
            endpoint_tested="/bookings/{booking_reference}",
            technical_justification="Service was not responding during automated assessment.",
        )

    # Step 1: Create a booking record tied specifically to USER_A or retrieve confirmed reference
    ref_a = _create_booking_for_user(USER_A_ID, USER_A_EMAIL, USER_A_NAME, USER_A_NIC, client)
    if not ref_a:
        ref_a = "RS-39230"

    # Step 2: Request booking reference omitting user_id completely
    resp = client.get(f"/bookings/{ref_a}")

    evidence = {
        "booking_reference": ref_a,
        "owner_user_id": USER_A_ID,
        "query_params_sent": {},
        "http_status": resp.status_code,
        "body_preview": resp.text[:250],
    }

    if resp.status_code == 200:
        status = "FAIL"
        obs = f"Omitting user_id completely bypassed authorization. HTTP 200 returned with full booking details for {ref_a}."
        concl = "CRITICAL AUTHORIZATION DEFICIENCY: booking-agent/main.py:391 check 'if user_id and booking.user_id ...' is bypassed when user_id is None."
        sev = SEVERITY_HIGH
        lik = LIKELIHOOD_HIGH
    elif resp.status_code in (401, 403):
        status = "PASS"
        obs = f"Access rejected with HTTP {resp.status_code} when user_id was omitted."
        concl = "Endpoint enforces mandatory user identity verification."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW
    else:
        status = "INCONCLUSIVE"
        obs = f"Endpoint responded with HTTP {resp.status_code}."
        concl = "Ownership bypass could not be confirmed."
        sev = SEVERITY_MEDIUM
        lik = LIKELIHOOD_MEDIUM

    return TestCaseResult(
        test_id="TC-PD-006",
        test_category="Authorization / IDOR",
        objective="Verify whether omitting user_id query parameter completely bypasses booking ownership enforcement",
        attack_scenario="Attacker discovers victim's booking reference and requests GET /bookings/{ref} with no user_id parameter.",
        input_request={"endpoint": f"/bookings/{ref_a}", "query_params": {}},
        expected_behaviour="Endpoint must require caller authentication and reject unverified requests (HTTP 401/403).",
        actual_behaviour=f"HTTP {resp.status_code}. Authorization bypassed on omission: {resp.status_code == 200}.",
        status=status,
        evidence=evidence,
        observation=obs,
        conclusion=concl,
        potential_impact="Permits anonymous enumeration and exfiltration of all passenger records if references are guessed or observed.",
        likelihood=lik,
        severity=sev,
        risk_level=compute_risk_level(sev, lik),
        endpoint_tested=f"/bookings/{ref_a}",
        technical_justification="In booking-agent/main.py:391, the ownership condition is only evaluated if user_id is truthy.",
    )


def run_tc_pd_008() -> TestCaseResult:
    """TC-PD-008: Unauthenticated Cancellation Endpoint."""
    client = get_client("booking")
    if not client:
        return TestCaseResult(
            test_id="TC-PD-008",
            test_category="Unauthenticated access",
            objective="Verify that cancellation management endpoints require authentication before exposing cancellation records",
            attack_scenario="Attacker accesses GET /cancellations to monitor refund claims and passenger travel cancellations.",
            input_request={"endpoint": "/cancellations"},
            expected_behaviour="Endpoint must require administrative or authenticated operator credentials (HTTP 401/403).",
            actual_behaviour="Booking service unavailable for assessment.",
            status="INCONCLUSIVE",
            evidence={"error": "Booking Agent client unavailable."},
            observation="Booking Agent could not be contacted to run cancellation queue probe.",
            conclusion="Testing is inconclusive due to environment reachability.",
            potential_impact="Exposure of passenger cancellation records, refund claims, and travel disruption histories.",
            likelihood=LIKELIHOOD_HIGH,
            severity=SEVERITY_MEDIUM,
            risk_level=SEVERITY_MEDIUM,
            endpoint_tested="/cancellations",
            technical_justification="Service was not responding during automated assessment.",
        )

    resp = client.get("/cancellations")

    evidence = {
        "http_status": resp.status_code,
        "content_length": len(resp.text),
        "body_preview": resp.text[:250],
    }

    if resp.status_code == 200:
        data = resp.json()
        count = len(data) if isinstance(data, list) else 0
        status = "FAIL"
        obs = f"GET /cancellations returned HTTP 200 with {count} cancellation records without requiring authentication."
        concl = "HIGH/MEDIUM DEFICIENCY: Cancellation cases and refund claims are exposed to unauthenticated callers."
        sev = SEVERITY_MEDIUM
        lik = LIKELIHOOD_HIGH
    elif resp.status_code in (401, 403):
        status = "PASS"
        obs = f"Access denied with HTTP {resp.status_code}. Authentication required."
        concl = "Cancellation management endpoint enforces authentication."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW
    else:
        status = "INCONCLUSIVE"
        obs = f"Unexpected response HTTP {resp.status_code}."
        concl = "Unable to evaluate authentication enforcement."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW

    return TestCaseResult(
        test_id="TC-PD-008",
        test_category="Unauthenticated access",
        objective="Verify that cancellation management endpoints require authentication before exposing cancellation records",
        attack_scenario="Attacker accesses GET /cancellations to monitor refund claims and passenger travel cancellations.",
        input_request={"method": "GET", "endpoint": "/cancellations", "auth": None},
        expected_behaviour="Endpoint must require administrative or authenticated operator credentials (HTTP 401/403).",
        actual_behaviour=f"HTTP {resp.status_code}. Public access allowed: {resp.status_code == 200}.",
        status=status,
        evidence=evidence,
        observation=obs,
        conclusion=concl,
        potential_impact="Allows competitors or unauthorized third parties to harvest railway refund cases and cancellation rates.",
        likelihood=lik,
        severity=sev,
        risk_level=compute_risk_level(sev, lik),
        endpoint_tested="/cancellations",
        technical_justification="Route booking-agent/main.py:608 defines list_cancellations with no Depends(require_auth) dependency.",
    )


def run_tc_pd_009() -> TestCaseResult:
    """TC-PD-009: Unauthorized Admin Endpoint Access."""
    client = get_client("booking")
    if not client:
        return TestCaseResult(
            test_id="TC-PD-009",
            test_category="Unauthorized Admin Endpoint Access",
            objective="Verify that administrative booking manifests cannot be retrieved without administrator credentials",
            attack_scenario="Attacker requests GET /admin/bookings to dump the complete passenger manifest for a travel date.",
            input_request={"endpoint": "/admin/bookings", "params": {"travel_date": FUTURE_TRAVEL_DATE}},
            expected_behaviour="Endpoint must strictly require administrator credentials / RBAC role (HTTP 401/403).",
            actual_behaviour="Booking service unavailable for assessment.",
            status="INCONCLUSIVE",
            evidence={"error": "Booking Agent client unavailable."},
            observation="Booking Agent could not be reached to test admin endpoint authorization.",
            conclusion="Testing is inconclusive due to environment reachability.",
            potential_impact="Mass extraction of passenger manifest, contact emails, and travel itineraries.",
            likelihood=LIKELIHOOD_HIGH,
            severity=SEVERITY_HIGH,
            risk_level=SEVERITY_HIGH,
            endpoint_tested="/admin/bookings",
            technical_justification="Service was not responding during automated assessment.",
        )

    resp = client.get("/admin/bookings", params={"travel_date": FUTURE_TRAVEL_DATE})

    evidence = {
        "http_status": resp.status_code,
        "headers": dict(resp.headers),
        "body_preview": resp.text[:300],
    }

    if resp.status_code == 200:
        data = resp.json() or {}
        count = data.get("count", 0)
        bookings = data.get("bookings", [])
        emails = [b.get("passenger_email") for b in bookings if b.get("passenger_email")]
        status = "FAIL"
        obs = f"GET /admin/bookings returned HTTP 200 with {count} passenger records without credentials. Sample emails: {emails[:2]}."
        concl = "CRITICAL ADMINISTRATIVE EXPOSURE: Full passenger manifests are reachable without authentication, directly violating Sri Lanka PDPA No. 9 of 2022."
        sev = SEVERITY_HIGH
        lik = LIKELIHOOD_HIGH
    elif resp.status_code in (401, 403):
        status = "PASS"
        obs = f"Access denied with HTTP {resp.status_code}. Admin authentication enforced."
        concl = "Administrative manifest endpoint enforces access control."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW
    else:
        status = "INCONCLUSIVE"
        obs = f"Endpoint returned HTTP {resp.status_code}."
        concl = "Could not confirm authorization enforcement."
        sev = SEVERITY_MEDIUM
        lik = LIKELIHOOD_MEDIUM

    return TestCaseResult(
        test_id="TC-PD-009",
        test_category="Unauthorized Admin Endpoint Access",
        objective="Verify that administrative booking manifests cannot be retrieved without administrator credentials",
        attack_scenario="Attacker requests GET /admin/bookings to dump the complete passenger manifest for a travel date.",
        input_request={"method": "GET", "endpoint": "/admin/bookings", "params": {"travel_date": FUTURE_TRAVEL_DATE}},
        expected_behaviour="Endpoint must strictly require administrator credentials / RBAC role (HTTP 401/403).",
        actual_behaviour=f"HTTP {resp.status_code}. Public manifest disclosure: {resp.status_code == 200}.",
        status=status,
        evidence=evidence,
        observation=obs,
        conclusion=concl,
        potential_impact="Mass leak of citizen travel patterns, contact emails, and payment statuses without any authentication.",
        likelihood=lik,
        severity=sev,
        risk_level=compute_risk_level(sev, lik),
        endpoint_tested="/admin/bookings",
        technical_justification="In booking-agent/main.py:829, list_admin_bookings has no authentication or role dependency.",
    )
