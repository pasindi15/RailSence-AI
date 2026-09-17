"""
security-agent/fraud/llm_summary.py
-----------------------------------
RailSense AI — Grounded LLM Advisory Summary for Security & Fraud Reviews.

Design & Governance:
1. Input: Sanitized evidence object ONLY (no raw NICs, no passwords, no tokens).
2. Four Explicit Grounded Sections:
   - observed_facts: Pure empirical measurements and context from features & request.
   - reasons_for_review: Specific anomaly triggers and thresholds crossed.
   - uncertainty: Epistemic limits of the algorithmic evaluation.
   - matters_to_check: Concrete verification checklist for human adjudicators.
3. RAG Policy Citations: Cites specific demo security policy sections.
4. Deterministic Fallback: Never fails if LLM API key or network is absent.
5. Project Demo Notice: Explicitly disclaimed as a project prototype specification.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


DEMO_POLICY_CITATIONS = [
    {
        "passage_id": "POL-SEC-004-ART-1",
        "citation": "DEMO-SEC-POL-01 §3.1",
        "title": "High-Velocity Reservation Limits",
        "description": "More than 2 booking attempts within 60 seconds triggers behavioral anomaly review.",
        "document_title": "Passenger Booking Anomaly Review Policy",
        "version": "v1.0",
        "status": "ACTIVE (DEMO / ACADEMIC SPECIFICATION)",
    },
    {
        "passage_id": "POL-SEC-004-ART-2",
        "citation": "DEMO-SEC-POL-02 §4.2",
        "title": "Overlapping Journey Conflict Detection",
        "description": "Simultaneous active journeys on differing train services require verification.",
        "document_title": "Passenger Booking Anomaly Review Policy",
        "version": "v1.0",
        "status": "ACTIVE (DEMO / ACADEMIC SPECIFICATION)",
    },
    {
        "passage_id": "POL-SEC-004-ART-3",
        "citation": "DEMO-SEC-POL-03 §2.4",
        "title": "Unusual Seat Volume Accumulation",
        "description": "Passenger identity accumulating >6 seats across multiple active bookings within 24 hours.",
        "document_title": "Passenger Booking Anomaly Review Policy",
        "version": "v1.0",
        "status": "ACTIVE (DEMO / ACADEMIC SPECIFICATION)",
    },
]


def get_security_policy_citations(query: str = "security review anomaly") -> list[dict[str, Any]]:
    """
    Retrieve applicable security review policies from the unified shared RAG knowledge base.
    Falls back gracefully to static demo specifications if unavailable.
    """
    try:
        _booking_agent_dir = Path(__file__).resolve().parent.parent.parent / "M3-Comunication-Hub&Booking-Agent" / "booking-agent"
        if str(_booking_agent_dir) not in sys.path:
            sys.path.insert(0, str(_booking_agent_dir))
        from cancellation.rag import retrieve_relevant_policies
        results = retrieve_relevant_policies(query=query, top_k=3, domain="security")
        if results:
            return [
                {
                    "passage_id": r.get("passage_id", "POL-SEC-ART-1"),
                    "citation": r.get("citation", ""),
                    "title": r.get("section", ""),
                    "description": r.get("content", "")[:180] + "...",
                    "document_title": r.get("document_title", "Passenger Booking Anomaly Review Policy"),
                    "version": r.get("version", "v1.0"),
                    "status": r.get("status", "ACTIVE (DEMO / ACADEMIC SPECIFICATION)"),
                }
                for r in results
            ]
    except Exception:
        pass
    return DEMO_POLICY_CITATIONS


def sanitize_evidence_object(evidence: dict[str, Any]) -> dict[str, Any]:
    """
    Strict privacy sanitization: strips raw NICs, tokens, and credentials.
    Replaces any plain Sri Lankan NIC patterns with masked surrogates.
    """
    sanitized: dict[str, Any] = {}
    for key, val in evidence.items():
        if key in (
            "auth_token", "jwt", "password", "secret", "api_key",
            "raw_nic", "nic_hash", "payment_secrets", "credentials",
        ):
            continue
        if isinstance(val, str):
            # Mask potential NICs: 9 digits + v/x or 12 digits
            masked = re.sub(r"\b(\d{5})\d{4}([vVxX]?)\b", r"\1****\2", val)
            masked = re.sub(r"\b(\d{6})\d{6}\b", r"\1******", masked)
            sanitized[key] = masked
        elif isinstance(val, dict):
            sanitized[key] = sanitize_evidence_object(val)
        elif isinstance(val, list):
            sanitized[key] = [
                sanitize_evidence_object(item) if isinstance(item, dict) else item
                for item in val
            ]
        else:
            sanitized[key] = val
    return sanitized


def generate_deterministic_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    """
    Procedural grounded summary generator conforming to the 4 required sections.
    Ensures zero hallucination, objective non-accusatory language, and complete determinism.
    """
    clean_ev = sanitize_evidence_object(evidence)

    # 0. Outage / Service Interruption Handling
    assessment_status = str(clean_ev.get("assessment_status", "SCORED")).upper()
    if assessment_status in ("ASSESSMENT_UNAVAILABLE", "OUTAGE", "UNAVAILABLE") or clean_ev.get("service_outage"):
        return {
            "observed_facts": [
                "Security ML scoring service was unreachable (service unavailable) at time of reservation evaluation.",
                "System continuity protocol engaged: reservation held in PENDING_FRAUD_REVIEW for manual administrative verification.",
            ],
            "reasons_for_review": [
                "Service connectivity interruption (status: ASSESSMENT_UNAVAILABLE). No behavioral anomaly or fraud is asserted.",
            ],
            "uncertainty": (
                "Automated risk scoring is unavailable due to an upstream service interruption. "
                "This condition does NOT indicate suspicious passenger behavior."
            ),
            "matters_to_check": [
                "Verify standard reservation details and payment confirmation.",
                "Confirm system connectivity status for the Security Agent before proceeding.",
            ],
            "policy_citations": get_security_policy_citations("continuity service interruption"),
            "risk_score": None,
            "risk_index": None,
            "risk_level": "PENDING_REVIEW",
            "model_version": "IsolationForest v1.0",
            "assessment_status": "ASSESSMENT_UNAVAILABLE",
            "is_fallback": True,
            "generation_status": "deterministic_fallback",
            "evaluation_source": "Administrative Continuity Protocol (Project Demo Specification)",
        }

    features = clean_ev.get("features", {})
    risk_score = float(clean_ev.get("risk_score", clean_ev.get("risk_index", 0.0)))
    risk_level = str(clean_ev.get("risk_level", "LOW")).upper()
    reasons = clean_ev.get("reasons", clean_ev.get("rule_triggers", []))
    ctx = clean_ev.get("travel_context", {})

    b_1m = features.get("bookings_last_1_minute", clean_ev.get("booking_count_1m", 0))
    b_10m = features.get("bookings_last_10_minutes", clean_ev.get("booking_count_10m", 0))
    b_24h = features.get("bookings_last_24_hours", clean_ev.get("booking_count_24h", 0))
    act_count = features.get("active_booking_count", clean_ev.get("active_bookings", 0))
    dup_attempts = features.get("duplicate_attempts", clean_ev.get("duplicate_count", 0))
    overlap_count = features.get("overlapping_trip_count", clean_ev.get("cross_train_conflicts", 0))
    sec_prev = features.get("seconds_since_previous_booking", clean_ev.get("seconds_since_prev", 999999.0))

    train_id = ctx.get("train_id", "N/A")
    route = f"{ctx.get('from_station', 'Unknown')} ➔ {ctx.get('to_station', 'Unknown')}"
    travel_date = ctx.get("travel_date", "N/A")
    p_count = ctx.get("passenger_count", 1)

    # 1. Observed Facts (Empirical Measurements Only)
    facts = [
        f"Route: {route} on train service {train_id} for travel date {travel_date}.",
        f"Requested passenger count: {p_count} seat(s).",
        f"Behavioral features extracted: {b_1m} booking(s) in last 1 minute, {b_10m} in last 10 minutes, and {b_24h} in last 24 hours.",
        f"Current active un-travelled bookings tied to this identity: {act_count}.",
    ]
    if sec_prev < 600:
        facts.append(f"Elapsed time since prior reservation request: {sec_prev:.0f} seconds.")
    if dup_attempts > 0:
        facts.append(f"Prior duplicate request attempts observed: {dup_attempts}.")
    if overlap_count > 0:
        facts.append(f"Concurrent journey time conflicts detected: {overlap_count}.")

    # 2. Reasons for Review (Objective Anomaly Indicators, Distinct from Feature Attribution)
    review_reasons = []
    matched_policies = []
    citations = get_security_policy_citations("velocity overlap volume")

    if b_1m > 1 or sec_prev < 60:
        review_reasons.append(f"High-velocity booking pattern: {b_1m} request(s) submitted within a 60-second window.")
        if len(citations) > 0:
            matched_policies.append(citations[0])
    if b_10m > 5:
        review_reasons.append(f"Elevated booking frequency: {b_10m} booking(s) registered in a 10-minute observation window.")
        if len(citations) > 0 and citations[0] not in matched_policies:
            matched_policies.append(citations[0])
    if overlap_count > 0:
        review_reasons.append("Cross-train time conflict: passenger identity has overlapping travel intervals with another active trip.")
        if len(citations) > 1:
            matched_policies.append(citations[1])
    if act_count > 4 or b_24h > 5:
        review_reasons.append("Unusual cumulative ticket accumulation across multiple railway services within 24 hours.")
        if len(citations) > 2:
            matched_policies.append(citations[2])
    if not review_reasons:
        for r in reasons:
            review_reasons.append(f"Behavioral anomaly indicator: {r}")
        if not review_reasons:
            review_reasons.append(f"IsolationForest normalized risk index ({risk_score:.4f}) crossed administrative review threshold.")

    # 3. Uncertainty (Clear Epistemic Limits; Legitimate Explanations Acknowledged)
    uncertainty = (
        "The model evaluates statistical deviations from typical booking intervals and computes a normalized risk index, "
        "but cannot determine intent or organizational context. "
        "Elevated booking frequency may correspond to legitimate group travel (e.g. tour operators, family groups, athletic teams) "
        "or urgent itinerary adjustments. Offline identity verification is required before administrative action."
    )

    # 4. Matters to Check (Actionable Checklist)
    matters = [
        "Check passenger contact email and masked identity records for historical travel regularity.",
        "Verify that passenger names in the reservation represent distinct individual travelers rather than automated placeholders.",
        "Check if passenger has contacted railway support regarding an urgent group reservation or itinerary correction.",
    ]
    if overlap_count > 0:
        matters.append("Contact passenger to clarify overlapping train service schedules.")

    return {
        "observed_facts": facts,
        "reasons_for_review": review_reasons,
        "uncertainty": uncertainty,
        "matters_to_check": matters,
        "policy_citations": matched_policies or citations,
        "risk_score": risk_score,
        "risk_index": round(risk_score, 4),
        "risk_level": risk_level,
        "model_version": "IsolationForest v1.0",
        "assessment_status": "SCORED",
        "is_fallback": True,
        "generation_status": "deterministic_fallback",
        "evaluation_source": "Deterministic Grounded Rule Base (Project Demo Specification)",
    }


def generate_grounded_fraud_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    """
    Main entry point for generating human-adjudicator advisory summaries.
    Uses Gemini LLM if API key is provided and valid, otherwise uses deterministic fallback.
    """
    clean_ev = sanitize_evidence_object(evidence)

    # Check for service outage
    if clean_ev.get("assessment_status") == "ASSESSMENT_UNAVAILABLE" or clean_ev.get("service_outage"):
        return generate_deterministic_summary(clean_ev)

    gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if not gemini_api_key or gemini_api_key.strip() in ("", "change-me", "your-api-key"):
        return generate_deterministic_summary(clean_ev)

    try:
        from google import genai
        client = genai.Client(api_key=gemini_api_key)
        citations = get_security_policy_citations()
        prompt = (
            "You are the RailSense AI Security & Fraud Grounded Adjudication Assistant.\n"
            "Analyze the following sanitized railway booking telemetry evidence and produce an advisory summary for human officers.\n"
            "Rules:\n"
            "- Strictly output valid JSON with 4 keys: observed_facts (list of str), reasons_for_review (list of str), uncertainty (str), matters_to_check (list of str).\n"
            "- Do NOT assert that the passenger committed fraud. Describe observations objectively (e.g. 'High-velocity booking pattern observed').\n"
            "- Keep rule-triggered observations distinct from model feature scores.\n"
            "- Present the risk score as a normalized 'risk index'.\n"
            "- Acknowledge that legitimate explanations (group travel, travel agents) may account for unusual velocity.\n"
            "- Only state facts present in the evidence. Never hallucinate names, NICs, or numbers.\n"
            "- Explicitly disclaim that this is a Project Demo Specification.\n\n"
            f"Evidence: {json.dumps(clean_ev, indent=2)}\n"
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = response.text or ""
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
            parsed["evaluation_source"] = "Grounded LLM (Gemini 2.5 Flash - Project Demo Specification)"
            parsed["policy_citations"] = citations
            parsed["risk_score"] = clean_ev.get("risk_score", 0.0)
            parsed["risk_index"] = round(float(clean_ev.get("risk_score", 0.0)), 4)
            parsed["risk_level"] = clean_ev.get("risk_level", "LOW")
            parsed["model_version"] = "IsolationForest v1.0"
            parsed["assessment_status"] = "SCORED"
            parsed["is_fallback"] = False
            parsed["generation_status"] = "llm_generated"
            return parsed
    except Exception:
        pass

    return generate_deterministic_summary(clean_ev)
