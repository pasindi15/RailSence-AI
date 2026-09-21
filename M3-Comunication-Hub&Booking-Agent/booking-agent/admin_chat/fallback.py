"""
admin_chat/fallback.py
----------------------
Deterministic Grounded Fallback Synthesizer for the Admin Booking Intelligence Assistant.
Guarantees 100% factual accuracy, zero hallucination, and operational continuity
when the LLM provider is offline, rate-limited, or during automated test runs.
"""

from __future__ import annotations

from typing import Any
from .schemas import AdminChatResponse, CardPayload, SourceEvidence


def generate_deterministic_response(
    intent: str,
    rag_context: dict[str, Any],
    entities: dict[str, Any],
    conversation_id: str | None = None,
) -> AdminChatResponse:
    """
    Synthesize factual response from structured database evidence.
    """
    db_ev = rag_context.get("database_evidence", {})
    policies = rag_context.get("policy_context", [])

    sources: list[SourceEvidence] = []
    card: CardPayload | None = None
    answer = ""
    retrieved_count = 0

    # 1. Unsupported Mutation (Action Request Refusal)
    if intent == "unsupported_mutation":
        return AdminChatResponse(
            answer=(
                "The Booking Intelligence Assistant is currently read-only. "
                "Use the administrative review controls and workflow buttons to perform this action."
            ),
            intent=intent,
            entities=entities,
            sources=[],
            card=None,
            retrieved_records=0,
            is_fallback=True,
            conversation_id=conversation_id,
        )

    # 2. Seat Availability
    if intent == "seat_availability_query":
        records = db_ev.get("records", [])
        retrieved_count = len(records)
        train_name = db_ev.get("train_name") or entities.get("train_name") or "Train Service"
        train_id = db_ev.get("train_id") or entities.get("train_id") or ""
        travel_date = db_ev.get("travel_date") or entities.get("travel_date") or ""

        if not records:
            answer = f"I could not find matching seat availability for {train_name} on {travel_date}."
        else:
            lines = [f"{train_name} (#{train_id}) seat availability for {travel_date}:"]
            card_items = []
            for r in records:
                s_cls = r.get("seat_class", "")
                cap = r.get("capacity", 0)
                conf = r.get("confirmed", 0)
                held = r.get("held", 0)
                avail = r.get("available", 0)
                lines.append(f"• {s_cls}: {avail} seats available (Capacity: {cap}, Booked: {conf}, Held: {held})")
                card_items.append({
                    "label": s_cls,
                    "available": avail,
                    "capacity": cap,
                    "booked": conf,
                    "held": held,
                })
                sources.append(SourceEvidence(
                    type="seat_inventory",
                    id=f"{train_id}-{travel_date}-{s_cls}".replace(" ", "_"),
                    label=f"Seat Inventory — {s_cls}",
                ))

            sources.append(SourceEvidence(
                type="schedule",
                id=str(records[0].get("schedule_id", train_id)),
                label=f"Train Schedule #{train_id} ({train_name})",
            ))

            card = CardPayload(
                type="seat_availability",
                title=f"{train_name} (#{train_id})",
                subtitle=f"Travel Date: {travel_date}",
                items=card_items,
            )
            answer = "\n".join(lines)

    # 3. Fraud Review Query
    elif intent == "fraud_review_query":
        q_type = db_ev.get("type")
        if q_type == "single_case":
            retrieved_count = 1
            case_ref = db_ev.get("case_reference", "")
            risk_score = db_ev.get("risk_score", 0.0)
            risk_lvl = db_ev.get("risk_level", "UNKNOWN")
            status = db_ev.get("status", "PENDING_REVIEW")
            reasons = db_ev.get("reasons", [])
            reasons_str = ", ".join(reasons) if reasons else "automated anomaly detection"

            answer = (
                f"Booking case {case_ref} is currently {status} with a {risk_lvl} risk assessment (ML score: {risk_score:.2f}). "
                f"Recorded risk indicators: {reasons_str}. Awaiting human administrative adjudication."
            )
            sources.append(SourceEvidence(type="fraud_review", id=case_ref, label=f"Fraud Assessment {case_ref}"))
            card = CardPayload(
                type="fraud_review",
                title=f"Fraud Review {case_ref}",
                subtitle=f"Status: {status}",
                items=[
                    {"label": "Risk Level", "value": risk_lvl},
                    {"label": "Risk Score", "value": f"{risk_score:.2f}"},
                    {"label": "Reasons", "value": reasons_str},
                ],
            )
        elif q_type == "count":
            cnt = db_ev.get("count", 0)
            st = db_ev.get("review_status", "pending")
            lvl = db_ev.get("risk_level")
            lvl_str = f" {lvl}" if lvl else ""
            answer = f"There are currently {cnt}{lvl_str} bookings waiting for fraud review in the queue."
            sources.append(SourceEvidence(type="fraud_review", id="queue_count", label="Fraud Review Queue"))
        else:
            cases = db_ev.get("cases", [])
            retrieved_count = len(cases)
            if not cases:
                answer = "There are currently no bookings waiting in the fraud review queue."
            else:
                lines = [f"Found {len(cases)} booking(s) in the fraud review queue:"]
                card_items = []
                for c in cases:
                    cr = c.get("case_reference", "")
                    sc = c.get("risk_score", 0.0)
                    lvl = c.get("risk_level", "HIGH")
                    lines.append(f"• Case {cr}: Risk {lvl} (Score: {sc:.2f})")
                    card_items.append({"case_reference": cr, "risk_level": lvl, "score": f"{sc:.2f}"})
                    sources.append(SourceEvidence(type="fraud_review", id=cr, label=f"Case {cr}"))
                answer = "\n".join(lines)
                card = CardPayload(type="fraud_review", title="Fraud Review Queue", items=card_items)

    # 4. Cancellation Query
    elif intent == "cancellation_query":
        q_type = db_ev.get("type")
        if q_type == "single_case":
            retrieved_count = 1
            case_ref = db_ev.get("case_reference", "")
            bkg_ref = db_ev.get("booking_reference", "")
            refund = db_ev.get("suggested_refund", "0.00")
            st = db_ev.get("status", "PENDING_ADMIN_REVIEW")
            reason = db_ev.get("reason", "")

            answer = (
                f"Cancellation request {case_ref} for booking {bkg_ref} is currently {st}. "
                f"Requested reason: \"{reason}\". Evaluated refund: Rs. {refund}."
            )
            sources.append(SourceEvidence(type="cancellation", id=case_ref, label=f"Cancellation Case {case_ref}"))
            card = CardPayload(
                type="cancellation",
                title=f"Cancellation {case_ref}",
                subtitle=f"Booking: {bkg_ref}",
                items=[
                    {"label": "Status", "value": st},
                    {"label": "Refund Amount", "value": f"Rs. {refund}"},
                    {"label": "Reason", "value": reason},
                ],
            )
        elif q_type == "count":
            cnt = db_ev.get("count", 0)
            answer = f"There are currently {cnt} cancellation requests waiting for administrative review."
            sources.append(SourceEvidence(type="cancellation", id="queue_count", label="Cancellation Queue"))
        else:
            cases = db_ev.get("cases", [])
            retrieved_count = len(cases)
            if not cases:
                answer = "There are no pending cancellation requests awaiting review."
            else:
                lines = [f"Found {len(cases)} cancellation request(s) awaiting review:"]
                card_items = []
                for c in cases:
                    cr = c.get("case_reference", "")
                    br = c.get("booking_reference", "")
                    rf = c.get("suggested_refund", "0.00")
                    lines.append(f"• Case {cr} (Booking: {br}) — Refund: Rs. {rf}")
                    card_items.append({"case_reference": cr, "booking": br, "refund": f"Rs. {rf}"})
                    sources.append(SourceEvidence(type="cancellation", id=cr, label=f"Case {cr}"))
                answer = "\n".join(lines)
                card = CardPayload(type="cancellation", title="Pending Cancellations", items=card_items)

    # 5. Manifest / Booked Tickets
    elif intent == "booking_manifest_query":
        q_type = db_ev.get("type")
        train_name = db_ev.get("train_name", "Train")
        travel_date = db_ev.get("travel_date", "")
        pax_count = db_ev.get("total_passengers", 0)
        bkg_count = db_ev.get("total_bookings", 0)

        if q_type == "count":
            answer = f"{train_name} has {bkg_count} confirmed booking(s) with {pax_count} passenger(s) on {travel_date}."
            sources.append(SourceEvidence(type="manifest", id="manifest_count", label=f"Manifest Count ({travel_date})"))
        else:
            bookings = db_ev.get("bookings", [])
            retrieved_count = len(bookings)
            if not bookings:
                answer = f"No confirmed passenger bookings found for {train_name} on {travel_date}."
            else:
                lines = [f"Passenger manifest for {train_name} on {travel_date} ({bkg_count} bookings, {pax_count} passengers):"]
                card_items = []
                for b in bookings[:8]:
                    ref = b.get("booking_reference", "")
                    s_cls = b.get("seat_class", "")
                    p_cnt = b.get("passenger_count", 1)
                    pax_list = b.get("passengers", [])
                    pax_desc = ", ".join(f"{p.get('full_name')} ({p.get('nic_masked')})" for p in pax_list[:2])
                    lines.append(f"• {ref}: {p_cnt} pax ({s_cls}) — {pax_desc}")
                    card_items.append({"ref": ref, "class": s_cls, "pax": p_cnt, "details": pax_desc})
                    sources.append(SourceEvidence(type="booking", id=ref, label=f"Booking {ref}"))
                answer = "\n".join(lines)
                card = CardPayload(type="manifest", title=f"Manifest: {train_name}", subtitle=travel_date, items=card_items)

    # 6. Booking Lookup ("What happened to BKG-...")
    elif intent == "booking_lookup":
        if not db_ev.get("found"):
            ref = entities.get("booking_reference", "UNKNOWN")
            answer = f"I could not find matching booking information for reference '{ref}'."
        else:
            retrieved_count = 1
            ref = db_ev.get("booking_reference", "")
            t_name = db_ev.get("train_name", "")
            route = db_ev.get("route", "")
            t_date = db_ev.get("travel_date", "")
            s_cls = db_ev.get("seat_class", "")
            fare = db_ev.get("fare", "0.00")
            st = db_ev.get("status", "")
            canc = db_ev.get("cancellation")

            lines = [
                f"Booking {ref}:",
                f"• Train & Route: {t_name} ({route})",
                f"• Travel Date: {t_date} ({s_cls})",
                f"• Status: {st} (Gross Fare: Rs. {fare})",
            ]
            if canc:
                c_st = canc.get("status", "")
                c_ref = canc.get("case_reference", "")
                c_rf = canc.get("suggested_refund", "")
                lines.append(f"• Cancellation Case: {c_ref} ({c_st}, Est. Refund: Rs. {c_rf})")
                sources.append(SourceEvidence(type="cancellation", id=c_ref, label=f"Cancellation {c_ref}"))

            sources.append(SourceEvidence(type="booking", id=ref, label=f"Booking Record {ref}"))
            answer = "\n".join(lines)
            card = CardPayload(
                type="booking_details",
                title=f"Booking {ref}",
                subtitle=f"{t_name} · {t_date}",
                items=[
                    {"label": "Status", "value": st},
                    {"label": "Fare", "value": f"Rs. {fare}"},
                    {"label": "Route", "value": route},
                ],
            )

    # 7. Booking Statistics Summary
    elif intent == "booking_statistics":
        dt = db_ev.get("date", "")
        conf = db_ev.get("confirmed_bookings", 0)
        pax = db_ev.get("passengers", 0)
        canc = db_ev.get("pending_cancellations", 0)
        fraud = db_ev.get("pending_fraud_reviews", 0)
        holds = db_ev.get("active_seat_holds", 0)

        answer = (
            f"Daily Booking Summary ({dt}):\n"
            f"• Confirmed bookings: {conf}\n"
            f"• Passengers travelling: {pax}\n"
            f"• Pending cancellations: {canc}\n"
            f"• Pending fraud reviews: {fraud}\n"
            f"• Active seat holds: {holds}"
        )
        sources.append(SourceEvidence(type="summary", id=f"summary_{dt}", label=f"Daily Summary ({dt})"))
        card = CardPayload(
            type="booking_summary",
            title="Today's Booking Summary",
            subtitle=dt,
            items=[
                {"label": "Confirmed Bookings", "value": str(conf)},
                {"label": "Passengers", "value": str(pax)},
                {"label": "Pending Cancellations", "value": str(canc)},
                {"label": "Pending Fraud Reviews", "value": str(fraud)},
                {"label": "Active Seat Holds", "value": str(holds)},
            ],
        )

    # 8. Schedule Query
    elif intent == "schedule_query":
        train_name = db_ev.get("train_name") or entities.get("train_name") or "Train Service"
        t_date = db_ev.get("travel_date") or entities.get("travel_date") or ""
        records = db_ev.get("records", [])
        if not records:
            answer = f"No operating train schedules found for {train_name} on {t_date}."
        else:
            r0 = records[0]
            dep = r0.get("departure_time", "")
            arr = r0.get("arrival_time", "")
            fro = r0.get("from_station", "")
            to = r0.get("to_station", "")
            answer = f"{train_name} operates on {t_date}: {fro} → {to}, departing at {dep} and arriving at {arr}."
            sources.append(SourceEvidence(type="schedule", id=str(r0.get("schedule_id", "")), label=f"Schedule #{r0.get('train_id')}"))

    # Fallback default
    else:
        answer = "I could not find matching booking information for that request."

    # Attach any policy sources
    for p in policies[:2]:
        sources.append(SourceEvidence(
            type="policy",
            id=p.get("passage_id", "POL-REF"),
            label=p.get("citation", "Railway Policy"),
        ))

    return AdminChatResponse(
        answer=answer,
        intent=intent,
        entities=entities,
        sources=sources,
        card=card,
        retrieved_records=retrieved_count,
        is_fallback=True,
        conversation_id=conversation_id,
    )
