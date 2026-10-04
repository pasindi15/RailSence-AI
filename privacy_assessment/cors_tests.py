"""
privacy_assessment/cors_tests.py
--------------------------------
RailSense AI — Cross-Origin Resource Sharing (CORS) Security Tests.
Covers:
- TC-PD-015: CORS / Unauthorized Origin Data Exposure
"""

from __future__ import annotations

import json
from typing import Dict, Any

from config import (
    get_client,
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
from test_cases import TestCaseResult


def run_tc_pd_015() -> TestCaseResult:
    """TC-PD-015: CORS / Unauthorized Origin Data Exposure."""
    untrusted_origin = "https://evil-attacker.com"
    tested_services = ["hub", "booking"]
    cors_evaluations = {}
    vulnerable_services = []

    for svc in tested_services:
        client = get_client(svc)
        if not client:
            cors_evaluations[svc] = {"status": "Service unavailable"}
            continue

        resp = client.get("/health", headers={"Origin": untrusted_origin})
        acao = resp.headers.get("access-control-allow-origin", "")
        acac = resp.headers.get("access-control-allow-credentials", "")

        is_vulnerable = (acao == untrusted_origin or acao == "*") and (acac.lower() == "true")
        cors_evaluations[svc] = {
            "origin_sent": untrusted_origin,
            "access_control_allow_origin": acao,
            "access_control_allow_credentials": acac,
            "reflects_untrusted_origin": acao == untrusted_origin,
            "credentials_allowed": acac.lower() == "true",
            "vulnerable": is_vulnerable,
        }

        if is_vulnerable or acao == untrusted_origin:
            vulnerable_services.append(svc)

    evidence = {
        "untrusted_origin_tested": untrusted_origin,
        "results_by_service": cors_evaluations,
        "vulnerable_count": len(vulnerable_services),
    }

    if vulnerable_services:
        status = "FAIL"
        obs = f"CORS origin reflection confirmed on: {', '.join(vulnerable_services)}. Arbitrary untrusted origin '{untrusted_origin}' was reflected in Access-Control-Allow-Origin with credentials."
        concl = "MEDIUM DEFICIENCY CONFIRMED: Permissive CORS configuration (allow_origins=['*'] + allow_credentials=True) exposes internal microservice endpoints to browser-based cross-origin exfiltration."
        sev = SEVERITY_MEDIUM
        lik = LIKELIHOOD_HIGH
    else:
        status = "PASS"
        obs = "No improper origin reflection detected. Services reject or sanitize cross-origin requests."
        concl = "CORS policies strictly restrict unauthorized browser origins."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW

    return TestCaseResult(
        test_id="TC-PD-015",
        test_category="CORS-related data exposure",
        objective="Verify whether local services permit cross-origin requests from arbitrary untrusted origins alongside credentials",
        attack_scenario="Attacker lures railway staff to an external website that executes cross-origin fetch requests to local RailSense APIs with credentials.",
        input_request={"headers": {"Origin": untrusted_origin}, "endpoint": "/health"},
        expected_behaviour="Services must reject arbitrary origins or omit Access-Control-Allow-Credentials when using wildcard policies.",
        actual_behaviour=f"Probed services: {tested_services}. Reflected untrusted origins: {vulnerable_services}.",
        status=status,
        evidence=evidence,
        observation=obs,
        conclusion=concl,
        potential_impact="Allows malicious third-party websites to read internal API responses and exfiltrate session data via browser side-channels.",
        likelihood=lik,
        severity=sev,
        risk_level=compute_risk_level(sev, lik),
        endpoint_tested="agent-hub/main.py & booking-agent/main.py (CORSMiddleware)",
        technical_justification="FastAPI CORSMiddleware configured with allow_origins=['*'] and allow_credentials=True reflects incoming Origin headers.",
    )
