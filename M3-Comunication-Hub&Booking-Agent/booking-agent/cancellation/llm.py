"""
cancellation/llm.py
-------------------
Grounded LLM Admin Advisory Synthesizer for RailSense AI.

Features:
1. Receives ONLY verified facts:
   - booking facts from Supabase (booking_reference, route, date, fare, class)
   - original passenger reason
   - NLP reason category
   - retrieved RAG policy evidence
   - deterministic eligibility result
   - deterministic suggested refund
2. Synthesizes a concise, professional, administrator-friendly advisory explanation
   using Google Gemini (gemini-3.6-flash).
3. Strict Human-in-the-Loop constraints:
   - The LLM is advisory only.
   - The LLM NEVER mutates booking status, decides authoritative eligibility,
     or approves/rejects requests.
4. Robust zero-crash fallback:
   - If Gemini is unreachable, offline, or unconfigured, falls back seamlessly
     to the deterministic grounded factual synthesizer.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from decimal import Decimal
from typing import Any


def is_test_environment() -> bool:
    """Check if running inside automated test environment."""
    return (
        "PYTEST_CURRENT_TEST" in os.environ
        or os.getenv("TESTING", "").lower() in ("1", "true")
        or any("pytest" in arg.lower() for arg in sys.argv)
    )


def _call_gemini_advisory(user_prompt: str, system_prompt: str) -> str | None:
    """
    Call Google Gemini API to synthesize grounded admin advisory summary.
    Attempts primary model (gemini-3.5-flash-lite) and fallback (gemini-3.6-flash).
    Returns generated text, or None on failure.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or not gemini_key.strip():
        return None

    primary_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    models_to_try = [primary_model]
    if primary_model != "gemini-3.6-flash":
        models_to_try.append("gemini-3.6-flash")

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"

        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {"parts": [{"text": user_prompt}]}
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 500,
            },
        }

        try:
            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                candidates = resp_data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        text = parts[0]["text"].strip()
                        if text:
                            return text
        except Exception:
            continue

    return None


def generate_admin_advisory_summary(
    booking_facts: dict[str, Any],
    passenger_reason: str,
    reason_category: str,
    policy_evidence: list[dict[str, Any]],
    eligibility: str,
    suggested_refund: Decimal | str,
    policy_rule_applied: str = "",
) -> str:
    """
    Generate a grounded advisory summary for the human administrator.
    Uses verified factual inputs only.
    """
    ref = booking_facts.get("booking_reference", "Unknown")
    route = f"{booking_facts.get('from_station', '')} to {booking_facts.get('to_station', '')}".strip()
    travel_date = booking_facts.get("travel_date", "")
    seat_class = booking_facts.get("seat_class", "")
    gross_fare = booking_facts.get("fare", "0.00")

    # Format human-friendly category label
    category_label = reason_category.replace("_", " ").title()

    # Evidence citation string
    citations = [c.get("citation", "") for c in policy_evidence if c.get("citation")]
    citation_str = ", ".join(citations[:2]) if citations else policy_rule_applied or "DEMO Policy Rules"

    # Determine recommendation
    if eligibility in ("ELIGIBLE", "FULL_REFUND"):
        recommendation = "Approve cancellation and authorize the calculated refund."
    elif eligibility == "PARTIAL_REFUND":
        recommendation = "Approve cancellation with standard partial refund deduction applied."
    else:
        recommendation = "Review passenger circumstances. Late notice policy recommends rejection of refund unless administrator exception applies."

    # In live application runtime, call Google Gemini
    if not is_test_environment() or os.getenv("USE_LIVE_LLM") == "1":
        system_prompt = (
            "You are an AI Rail Operations Advisory Assistant for RailSense AI. "
            "You provide grounded, objective, concise advisory summaries for human administrators. "
            "You MUST NOT invent facts, alter figures, or attempt to execute administrative decisions. "
            "Your role is strictly advisory. "
            "Always include the booking reference, route, gross fare, and recommended action in your briefing."
        )
        user_msg = (
            f"Booking: {ref} ({route} on {travel_date}, {seat_class}, Fare: Rs. {gross_fare})\n"
            f"Passenger Reason: \"{passenger_reason}\"\n"
            f"NLP Category: {category_label}\n"
            f"Retrieved Policy Evidence: {citation_str}\n"
            f"Policy Rule Applied: {policy_rule_applied}\n"
            f"Deterministic Eligibility: {eligibility}\n"
            f"Suggested Refund: Rs. {suggested_refund}\n"
            f"Advisory Recommendation: {recommendation}\n\n"
            "Synthesize a concise 3-4 sentence administrator briefing summarizing the case, policy adherence, "
            "and recommended administrative action."
        )

        # 1. Try Google Gemini
        gemini_summary = _call_gemini_advisory(user_prompt=user_msg, system_prompt=system_prompt)
        if gemini_summary:
            return gemini_summary

        # 2. Try Anthropic fallback if configured
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=anthropic_key)
                resp = client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=250,
                    temperature=0.0,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_msg}],
                )
                if resp.content and len(resp.content) > 0:
                    return resp.content[0].text.strip()
            except Exception:
                pass

    # Factual Grounded Template Synthesizer (100% reliable, zero hallucination fallback)
    summary_lines = [
        f"Booking {ref} ({route} on {travel_date}, {seat_class}, Gross Fare: Rs. {gross_fare}) was requested for cancellation.",
        f"Passenger Reason: \"{passenger_reason}\" (Classified as: {category_label}).",
        f"Policy Evidence: Evaluated under {citation_str}. {policy_rule_applied}.",
        f"System Evaluation: Eligibility status is '{eligibility}' with a calculated suggested refund of Rs. {suggested_refund}.",
        f"Recommended Action: {recommendation}",
    ]

    return "\n".join(summary_lines)
