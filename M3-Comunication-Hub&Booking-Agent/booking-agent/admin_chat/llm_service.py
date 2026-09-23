"""
admin_chat/llm_service.py
-------------------------
Grounded LLM Natural-Language Answer Generation & Factual Consistency Verification
for the Admin Booking Intelligence Assistant.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.request
from typing import Any

from .fallback import generate_deterministic_response
from .schemas import AdminChatResponse, CardPayload, SourceEvidence

logger = logging.getLogger(__name__)


def is_test_environment() -> bool:
    """Check if running in an automated test environment."""
    return (
        "PYTEST_CURRENT_TEST" in os.environ
        or os.getenv("TESTING", "").lower() in ("1", "true")
        or any("pytest" in arg.lower() for arg in sys.argv)
    )


def verify_factual_consistency(
    answer: str,
    rag_context: dict[str, Any],
) -> tuple[bool, list[str]]:
    """
    Verify that critical factual figures (seat counts, refund amounts, booking references)
    mentioned in the LLM's answer match the underlying database evidence.
    """
    discrepancies = []
    db_ev = rag_context.get("database_evidence", {})

    # 1. Booking Reference check
    b_ref = db_ev.get("booking_reference")
    if b_ref:
        wrong_refs = re.findall(r"\b((?:RS|BKG)-\d{4,6})\b", answer, re.IGNORECASE)
        for wr in wrong_refs:
            if wr.upper() != b_ref.upper():
                discrepancies.append(f"Mismatched booking reference: '{wr}' != '{b_ref}'")

    # 2. Seat Availability check
    records = db_ev.get("records", [])
    if records and isinstance(records, list):
        for r in records:
            avail = r.get("available")
            s_cls = r.get("seat_class", "")
            if s_cls.lower() in answer.lower() and avail is not None:
                prefix_match = re.search(rf"(?i)(\d+)\s+(?:available\s+)?(?:seats?\s+)?(?:available\s+)?(?:on\s+|for\s+|in\s+)?{re.escape(s_cls)}", answer)
                suffix_match = re.search(rf"(?i){re.escape(s_cls)}[^\d\n]*?(\d+)", answer)

                valid_numbers = {avail, r.get("capacity"), r.get("confirmed"), r.get("held")}
                stated_num = None
                if prefix_match:
                    stated_num = int(prefix_match.group(1))
                elif suffix_match:
                    stated_num = int(suffix_match.group(1))

                if stated_num is not None and stated_num not in valid_numbers:
                    discrepancies.append(f"Inconsistent seat availability for {s_cls}: stated {stated_num}, actual {avail}")

    # 3. Fraud case counts
    tot_fraud = db_ev.get("count") or db_ev.get("total_flagged")
    if tot_fraud is not None:
        for m in re.findall(r"\b(\d+)\s+(?:flagged|pending|fraud)\b", answer, re.IGNORECASE):
            if int(m) != tot_fraud:
                discrepancies.append(f"Answer mentions {m} cases, but DB has {tot_fraud}.")

    # 4. Cancellation counts
    tot_canc = db_ev.get("count") or db_ev.get("total_pending")
    if tot_canc is not None:
        for m in re.findall(r"\b(\d+)\s+(?:cancellations?|pending)\b", answer, re.IGNORECASE):
            if int(m) != tot_canc:
                discrepancies.append(f"Answer mentions {m} cancellations, but DB has {tot_canc}.")

    # 5. False 'not found' guard: if the evidence proves the record exists
    # (found: true), the LLM must not claim it could not find it. This keeps
    # LLM answers consistent with the deterministic fallback for the same data.
    if db_ev.get("found"):
        not_found_phrases = (
            "could not find matching booking information",
            "could not find a booking",
            "no booking found",
            "booking was not found",
            "not found in the railsense database",
        )
        answer_lower = answer.lower()
        if any(phrase in answer_lower for phrase in not_found_phrases):
            discrepancies.append(
                "LLM claimed the record was not found, but database evidence has found: true."
            )

    return (len(discrepancies) == 0, discrepancies)


def _call_gemini_chat(
    query: str,
    rag_context: dict[str, Any],
    entities: dict[str, Any],
) -> dict[str, Any] | None:
    """Call Google Gemini Generative AI API using urllib."""
    gemini_key = (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("M3_GEMINI_KEY")
    )
    if not gemini_key:
        return None

    models_to_try = [
        os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"),
        "gemini-flash-latest",
        "gemini-pro-latest",
    ]

    system_prompt = (
        "You are the RailSense AI Admin Booking Intelligence Assistant.\n"
        "Your role is strictly READ-ONLY. You provide concise, factual explanations of live railway booking data.\n"
        "Rules:\n"
        "1. Never invent or hallucinate seat numbers, availability counts, refund figures, risk scores, or booking references.\n"
        "2. Ground every single claim in the provided EVIDENCE dictionary.\n"
        "3. If a specific booking reference, cancellation case, or fraud case was queried but found is False in evidence, clearly state that the reference (e.g. RS-12345 or CR-12345) was not found in the RailSense database.\n"
        "4. CRITICAL - found flag rule: If evidence contains found: true, the record EXISTS. Never say the record was not found, and never use the phrase 'I could not find matching booking information' for that record. Report the fields the evidence actually contains (including passenger_email when present).\n"
        "5. If evidence contains found: true but a requested field is null/missing (e.g. passenger_email), state that the specific field is not recorded for that booking, and still report all other fields.\n"
        "6. Never approve, cancel, or modify any database records. If asked to modify, refuse and direct the user to administrative review controls.\n"
        "7. Output valid JSON matching this schema:\n"
        "   {\n"
        "     \"answer\": \"concise natural language explanation\",\n"
        "     \"sources\": [{\"type\": \"...\", \"id\": \"...\", \"label\": \"...\"}],\n"
        "     \"card\": null or {\"type\": \"...\", \"title\": \"...\", \"subtitle\": \"...\", \"items\": [{\"label\": \"...\", \"value\": \"...\"}]}\n"
        "   }"
    )

    user_prompt = f"User Question: {query}\n\nEvidence: {json.dumps(rag_context, indent=2)}"

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 2048,
                "response_mime_type": "application/json",
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
            with urllib.request.urlopen(req, timeout=7.0) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                candidates = resp_data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        raw_json = parts[0]["text"].strip()
                        return json.loads(raw_json)
        except Exception as e:
            logger.debug(f"Gemini model {model} attempt error: {e}")
            continue

    return None


def generate_chat_response(
    intent: str,
    rag_context: dict[str, Any],
    entities: dict[str, Any],
    conversation_id: str | None = None,
) -> AdminChatResponse:
    """
    Main entry point: Generates a grounded response using Gemini LLM if available,
    validates factual consistency against database evidence, and falls back
    to deterministic synthesizer if unavailable or invalid.
    """
    query = rag_context.get("query", "")

    # Live LLM execution if not in test environment or explicitly enabled
    if not is_test_environment() or os.getenv("USE_LIVE_LLM") == "1":
        try:
            llm_out = _call_gemini_chat(query, rag_context, entities)
            if llm_out and isinstance(llm_out, dict) and "answer" in llm_out:
                answer_text = llm_out["answer"]

                # Factual consistency validation
                is_valid, discrepancies = verify_factual_consistency(answer_text, rag_context)
                if is_valid:
                    sources_data = [
                        SourceEvidence(**s) for s in llm_out.get("sources", [])
                        if isinstance(s, dict) and "type" in s and "id" in s and "label" in s
                    ]
                    card_data = None
                    if llm_out.get("card") and isinstance(llm_out["card"], dict):
                        try:
                            card_data = CardPayload(**llm_out["card"])
                        except Exception as e:
                            logger.warning(f"Failed to instantiate CardPayload from LLM card: {e}")
                            card_data = None

                    db_ev = rag_context.get("database_evidence", {})
                    rec_count = len(db_ev.get("records", [])) if "records" in db_ev else (1 if db_ev else 0)

                    return AdminChatResponse(
                        answer=answer_text,
                        intent=intent,
                        entities=entities,
                        sources=sources_data,
                        card=card_data,
                        retrieved_records=rec_count,
                        is_fallback=False,
                        conversation_id=conversation_id,
                    )
        except Exception as err:
            logger.warning(f"Live LLM generation encountered error: {err}. Falling back to deterministic synthesizer.")

    # Deterministic fallback synthesizer
    return generate_deterministic_response(
        intent=intent,
        rag_context=rag_context,
        entities=entities,
        conversation_id=conversation_id,
    )
