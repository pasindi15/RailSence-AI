"""
privacy_assessment/memory_tests.py
----------------------------------
RailSense AI — Operational Queue & Topology Data Exposure Security Tests.
Replaces offline conversational tests with active, fully evaluated M3 boundaries:
- TC-PD-010: Unauthenticated Fraud Review Queue Disclosure (/internal/fraud-reviews)
- TC-PD-011: Unauthenticated Service Topology & Agent Registry Disclosure (/api/hub/dashboard)
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
from pii_scanner import PIIScanner
from test_cases import TestCaseResult


def run_tc_pd_010() -> TestCaseResult:
    """TC-PD-010: Unauthenticated Fraud Review Queue Disclosure."""
    client = get_client("booking")
    if not client:
        return TestCaseResult(
            test_id="TC-PD-010",
            test_category="Unauthenticated access",
            objective="Verify that internal fraud screening review queues require authentication before exposing flagged cases",
            attack_scenario="Adversary queries GET /internal/fraud-reviews without authentication to extract flagged passenger cases and risk scores.",
            input_request={"endpoint": "/internal/fraud-reviews"},
            expected_behaviour="Internal fraud queue must strictly require authentication or administrative role (HTTP 401/403).",
            actual_behaviour="Booking service unavailable for assessment.",
            status="INCONCLUSIVE",
            evidence={"error": "Booking Agent client unavailable."},
            observation="Booking Agent could not be contacted to run fraud queue probe.",
            conclusion="Testing is inconclusive due to environment reachability.",
            potential_impact="Exposure of flagged citizen travel requests and fraud scoring indicators.",
            likelihood=LIKELIHOOD_HIGH,
            severity=SEVERITY_MEDIUM,
            risk_level=SEVERITY_MEDIUM,
            endpoint_tested="/internal/fraud-reviews",
            technical_justification="Service was not responding during automated assessment.",
        )

    resp = client.get("/internal/fraud-reviews")

    evidence = {
        "http_status": resp.status_code,
        "content_length": len(resp.text),
        "body_preview": resp.text[:300],
    }

    if resp.status_code == 200:
        data = resp.json()
        count = len(data) if isinstance(data, list) else 0
        status = "FAIL"
        obs = f"GET /internal/fraud-reviews returned HTTP 200 without authentication. Discloses {count} flagged passenger fraud cases."
        concl = "MEDIUM DEFICIENCY CONFIRMED: Internal security and fraud adjudication records are accessible to anonymous callers."
        sev = SEVERITY_MEDIUM
        lik = LIKELIHOOD_HIGH
    elif resp.status_code in (401, 403):
        status = "PASS"
        obs = f"Access denied with HTTP {resp.status_code}. Authentication required."
        concl = "Fraud review queue enforces authentication."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW
    else:
        status = "INCONCLUSIVE"
        obs = f"Endpoint responded with HTTP {resp.status_code}."
        concl = "Unable to evaluate fraud queue access control."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW

    return TestCaseResult(
        test_id="TC-PD-010",
        test_category="Unauthenticated access",
        objective="Verify that internal fraud screening review queues require authentication before exposing flagged cases",
        attack_scenario="Adversary queries GET /internal/fraud-reviews without authentication to extract flagged passenger cases and risk scores.",
        input_request={"method": "GET", "endpoint": "/internal/fraud-reviews", "headers": {"Authorization": None}},
        expected_behaviour="Internal fraud queue must strictly require authentication or administrative role (HTTP 401/403).",
        actual_behaviour=f"HTTP {resp.status_code}. Anonymous access permitted: {resp.status_code == 200}.",
        status=status,
        evidence=evidence,
        observation=obs,
        conclusion=concl,
        potential_impact="Exposes flagged traveler identities, risk evaluation metrics, and adjudication notes to unauthorized actors.",
        likelihood=lik,
        severity=sev,
        risk_level=compute_risk_level(sev, lik),
        endpoint_tested="/internal/fraud-reviews",
        technical_justification="In booking-agent/main.py:704, list_fraud_reviews() does not declare an authentication dependency.",
    )


def run_tc_pd_011() -> TestCaseResult:
    """TC-PD-011: Unauthenticated Service Topology & Agent Registry Disclosure."""
    client = get_client("hub")
    if not client:
        return TestCaseResult(
            test_id="TC-PD-011",
            test_category="Sensitive Information Leakage",
            objective="Verify that Central Hub observability dashboard does not disclose internal microservice topology and addresses without auth",
            attack_scenario="Adversary queries GET /api/hub/dashboard to map the internal microservice architecture, private IP bindings, and agent URLs.",
            input_request={"endpoint": "/api/hub/dashboard"},
            expected_behaviour="Observability metrics and internal service topologies must require administrator authentication (HTTP 401/403).",
            actual_behaviour="Central Hub service unavailable for assessment.",
            status="INCONCLUSIVE",
            evidence={"error": "Agent Hub client unavailable."},
            observation="Central Hub could not be contacted to run topology disclosure probe.",
            conclusion="Testing is inconclusive due to environment reachability.",
            potential_impact="Internal service reconnaissance enables targeted lateral movement across private agent RPCs.",
            likelihood=LIKELIHOOD_HIGH,
            severity=SEVERITY_MEDIUM,
            risk_level=SEVERITY_MEDIUM,
            endpoint_tested="/api/hub/dashboard",
            technical_justification="Service was not responding during automated assessment.",
        )

    resp = client.get("/api/hub/dashboard")

    evidence = {
        "http_status": resp.status_code,
        "content_length": len(resp.text),
        "body_preview": resp.text[:300],
    }

    if resp.status_code == 200:
        data = resp.json() or {}
        agents = data.get("agents", [])
        agent_names = [a.get("name") for a in agents if a.get("name")]
        agent_urls = [a.get("base_url") for a in agents if a.get("base_url")]
        status = "FAIL"
        obs = f"GET /api/hub/dashboard returned HTTP 200 without authentication. Discloses {len(agents)} registered agent services: {agent_names}, URLs: {agent_urls}."
        concl = "MEDIUM DEFICIENCY CONFIRMED: System topology, agent network registry, and loopback URLs are exposed to unauthenticated callers."
        sev = SEVERITY_MEDIUM
        lik = LIKELIHOOD_HIGH
    elif resp.status_code in (401, 403):
        status = "PASS"
        obs = f"Access denied with HTTP {resp.status_code}. Dashboard requires authentication."
        concl = "Observability dashboard is protected."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW
    else:
        status = "INCONCLUSIVE"
        obs = f"Endpoint responded with HTTP {resp.status_code}."
        concl = "Unable to assess dashboard access control."
        sev = SEVERITY_LOW
        lik = LIKELIHOOD_LOW

    return TestCaseResult(
        test_id="TC-PD-011",
        test_category="Sensitive Information Leakage",
        objective="Verify that Central Hub observability dashboard does not disclose internal microservice topology and addresses without auth",
        attack_scenario="Adversary queries GET /api/hub/dashboard to map the internal microservice architecture, private IP bindings, and agent URLs.",
        input_request={"method": "GET", "endpoint": "/api/hub/dashboard", "headers": {"Authorization": None}},
        expected_behaviour="Observability metrics and internal service topologies must require administrator authentication (HTTP 401/403).",
        actual_behaviour=f"HTTP {resp.status_code}. Network topology disclosed: {resp.status_code == 200}.",
        status=status,
        evidence=evidence,
        observation=obs,
        conclusion=concl,
        potential_impact="Facilitates attacker reconnaissance by exposing internal RPC endpoints, agent topologies, and circuit breaker states.",
        likelihood=lik,
        severity=sev,
        risk_level=compute_risk_level(sev, lik),
        endpoint_tested="/api/hub/dashboard",
        technical_justification="In agent-hub/main.py:184, get_hub_dashboard() lacks authentication or role dependencies.",
    )
