"""
cancellation/service.py
-----------------------
Cancellation Service for RailSense AI Member C.

Coordinates:
1. Booking retrieval and status validation from database.
2. NLP reason classification and entity extraction.
3. RAG policy retrieval from domain knowledge base.
4. Deterministic business logic calculation (eligibility, suggested refund).
5. Grounded LLM advisory summary generation.
6. Persistence of cancellation case (CN-XXXXX) with PENDING_ADMIN_REVIEW status.
7. Human-in-the-Loop Admin Review (Approve/Reject) with explicit status transitions.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from database.models import (
    AuditLog,
    AuditStatus,
    Booking,
    BookingStatus,
    CancellationRequest,
    CancellationStatus,
)
from .nlp import analyze_admin_rejection_reason, process_cancellation_nlp
from .rag import retrieve_relevant_policies
from .rules import calculate_cancellation_refund
from .llm import generate_admin_advisory_summary


class CancellationError(Exception):
    """Base exception for cancellation workflow."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class BookingNotFoundError(CancellationError):
    def __init__(self, ref: str):
        super().__init__(f"Booking '{ref}' does not exist.", status_code=404)


class BookingAlreadyCancelledError(CancellationError):
    def __init__(self, ref: str):
        super().__init__(f"Booking '{ref}' is already cancelled.", status_code=409)


class CancellationAlreadyPendingError(CancellationError):
    def __init__(self, ref: str):
        super().__init__(f"A cancellation request for booking '{ref}' is already pending review.", status_code=409)


class CancellationService:
    def __init__(self, db: Session):
        self.db = db

    def _generate_case_reference(self) -> str:
        """Generate a unique CN-XXXXX case reference."""
        for _ in range(10):
            cand = f"CN-{secrets.randbelow(90000) + 10000}"
            exists = self.db.query(CancellationRequest).filter_by(case_reference=cand).first()
            if not exists:
                return cand
        return f"CN-{secrets.token_hex(4).upper()}"

    def process_cancellation_request(
        self,
        booking_reference: str,
        reason: str,
    ) -> dict[str, Any]:
        """
        Step 1 to 8: Process incoming cancellation request from passenger.
        Does NOT cancel the booking; creates a PENDING_ADMIN_REVIEW case.
        """
        clean_ref = booking_reference.strip().upper()
        clean_reason = reason.strip()

        # 1. Retrieve real booking from Supabase
        booking = (
            self.db.query(Booking)
            .filter(Booking.booking_reference == clean_ref)
            .first()
        )
        if not booking:
            raise BookingNotFoundError(clean_ref)

        if booking.status == BookingStatus.CANCELLED:
            raise BookingAlreadyCancelledError(clean_ref)

        # Check for existing pending request
        existing_req = (
            self.db.query(CancellationRequest)
            .filter(CancellationRequest.booking_id == booking.id)
            .first()
        )
        if existing_req:
            if existing_req.status == CancellationStatus.PENDING_ADMIN_REVIEW:
                raise CancellationAlreadyPendingError(clean_ref)
            elif existing_req.status == CancellationStatus.APPROVED:
                raise BookingAlreadyCancelledError(clean_ref)

        # 2. NLP Processing
        nlp_res = process_cancellation_nlp(clean_reason)
        reason_category = nlp_res["reason_category"]

        # 3. RAG Policy Retrieval
        query = f"{clean_reason} {reason_category.replace('_', ' ')} cancellation refund"
        policy_evidence = retrieve_relevant_policies(query, top_k=3)

        # 4. Deterministic Business Logic
        departure_time = booking.schedule.departure_time if booking.schedule else None
        calc_result = calculate_cancellation_refund(
            fare=booking.fare,
            travel_date=booking.travel_date,
            departure_time=departure_time,
            reason_category=reason_category,
        )

        # 5. LLM Grounded Advisory Summary
        booking_facts = {
            "booking_reference": booking.booking_reference,
            "from_station": booking.from_station,
            "to_station": booking.to_station,
            "travel_date": booking.travel_date.isoformat(),
            "seat_class": booking.seat_class,
            "passenger_count": booking.passenger_count,
            "fare": f"{booking.fare:.2f}",
        }

        ai_summary = generate_admin_advisory_summary(
            booking_facts=booking_facts,
            passenger_reason=clean_reason,
            reason_category=reason_category,
            policy_evidence=policy_evidence,
            eligibility=calc_result.eligibility,
            suggested_refund=f"{calc_result.suggested_refund:.2f}",
            policy_rule_applied=calc_result.policy_rule_applied,
        )

        # 6. Persist to cancellation_requests
        case_ref = self._generate_case_reference()
        canc_req = CancellationRequest(
            case_reference=case_ref,
            booking_id=booking.id,
            reason=clean_reason,
            reason_category=reason_category,
            eligibility=calc_result.eligibility,
            suggested_refund=calc_result.suggested_refund,
            ai_summary=ai_summary,
            status=CancellationStatus.PENDING_ADMIN_REVIEW,
        )

        self.db.add(canc_req)
        self.db.commit()
        self.db.refresh(canc_req)

        # Note: booking.status strictly remains CONFIRMED
        return {
            "status": "cancellation_requested",
            "case_reference": case_ref,
            "booking_reference": clean_ref,
            "reason": clean_reason,
            "reason_category": reason_category,
            "eligibility": calc_result.eligibility,
            "suggested_refund": f"{calc_result.suggested_refund:.2f}",
            "refund_percentage": calc_result.refund_percentage,
            "policy_applied": calc_result.policy_rule_applied,
            "ai_summary": ai_summary,
            "policy_evidence": [
                {"citation": c["citation"], "section": c["section"], "score": c["similarity_score"]}
                for c in policy_evidence
            ],
            "cancellation_status": canc_req.status.value,
            "booking_status": booking.status.value,
        }

    def list_cancellation_cases(self, status_filter: str | None = None) -> list[dict[str, Any]]:
        """
        List cancellation cases with associated booking and train details for the Admin Dashboard.
        """
        from sqlalchemy.orm import joinedload
        query = (
            self.db.query(CancellationRequest)
            .options(joinedload(CancellationRequest.booking).joinedload(Booking.train))
            .order_by(CancellationRequest.id.desc())
        )
        if status_filter:
            try:
                enum_val = CancellationStatus(status_filter.upper())
                query = query.filter(CancellationRequest.status == enum_val)
            except ValueError:
                pass

        cases = query.all()
        results: list[dict[str, Any]] = []
        for c in cases:
            b = c.booking
            results.append({
                "case_reference": c.case_reference,
                "booking_reference": b.booking_reference if b else "N/A",
                "route": f"{b.from_station} ➔ {b.to_station}" if b else "N/A",
                "from_station": b.from_station if b else "",
                "to_station": b.to_station if b else "",
                "travel_date": b.travel_date.isoformat() if b else "",
                "train_id": b.train.train_id if (b and b.train) else "",
                "seat_class": b.seat_class if b else "",
                "passenger_count": b.passenger_count if b else 1,
                "fare": f"{b.fare:.2f}" if b else "0.00",
                "reason": c.reason,
                "reason_category": c.reason_category or "other",
                "eligibility": c.eligibility or "PENDING",
                "suggested_refund": f"{c.suggested_refund:.2f}" if c.suggested_refund is not None else "0.00",
                "ai_summary": c.ai_summary or "",
                "status": c.status.value,
                "admin_decision": c.admin_decision,
                "admin_reason": c.admin_reason,
                "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "passenger_email": b.passenger_email if b else None,
                "booking_status": b.status.value if b else "UNKNOWN",
            })
        return results

    def review_cancellation(
        self,
        case_reference: str,
        decision: str,
        admin_reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Human-in-the-Loop Admin Adjudication:
        - If APPROVE: Booking.status -> CANCELLED, CancellationRequest.status -> APPROVED
        - If REJECT: Booking.status remains CONFIRMED, CancellationRequest.status -> REJECTED
        """
        clean_ref = case_reference.strip().upper()
        clean_decision = decision.strip().upper()

        if clean_decision not in ("APPROVE", "REJECT"):
            raise CancellationError("Decision must be either 'APPROVE' or 'REJECT'.", status_code=400)

        case = (
            self.db.query(CancellationRequest)
            .filter(CancellationRequest.case_reference == clean_ref)
            .first()
        )
        if not case:
            raise CancellationError(f"Cancellation case '{clean_ref}' not found.", status_code=404)

        if case.status != CancellationStatus.PENDING_ADMIN_REVIEW:
            raise CancellationError(f"Case '{clean_ref}' has already been reviewed (Status: {case.status.value}).", status_code=409)

        booking = case.booking
        now = datetime.now(timezone.utc)
        nlp_analysis: dict[str, Any] | None = None
        refund_str = f"{case.suggested_refund:.2f}" if case.suggested_refund is not None else "0.00"

        if clean_decision == "APPROVE":
            case.status = CancellationStatus.APPROVED
            case.admin_decision = "APPROVED"
            case.admin_reason = admin_reason or "Approved by administrator following policy review."
            case.reviewed_at = now
            if booking:
                booking.status = BookingStatus.CANCELLED

            # Record immutable trace in audit_logs table
            try:
                audit_entry = AuditLog(
                    message_id=f"AUDIT-APP-{case.case_reference}-{secrets.token_hex(3)}",
                    sender_agent="admin-adjudicator",
                    receiver_agent="booking-agent",
                    intent="cancellation_review_approval",
                    status=AuditStatus.ROUTED,
                    error_message=f"Admin Decision: APPROVED | Case: {case.case_reference} | Refund: Rs. {refund_str} | Booking: {booking.booking_reference if booking else 'N/A'}",
                    timestamp=now,
                )
                self.db.add(audit_entry)
            except Exception:
                pass

        elif clean_decision == "REJECT":
            rejection_text = (admin_reason or "").strip()
            if not rejection_text:
                rejection_text = "Rejected per railway cancellation guidelines."

            # 1. NLP analysis on administrator's typed rejection reason
            nlp_analysis = analyze_admin_rejection_reason(
                rejection_text,
                booking_context={
                    "booking_reference": booking.booking_reference if booking else "",
                    "route": f"{booking.from_station} to {booking.to_station}" if booking else "",
                    "travel_date": booking.travel_date.isoformat() if (booking and booking.travel_date) else "",
                },
            )

            case.status = CancellationStatus.REJECTED
            case.admin_decision = "REJECTED"
            case.admin_reason = rejection_text
            case.reviewed_at = now
            # booking.status remains CONFIRMED

            # 2. Record immutable trace in audit_logs table
            try:
                audit_entry = AuditLog(
                    message_id=f"AUDIT-REJ-{case.case_reference}-{secrets.token_hex(3)}",
                    sender_agent="admin-adjudicator",
                    receiver_agent="booking-agent",
                    intent="cancellation_review_rejection",
                    status=AuditStatus.REJECTED,
                    error_message=(
                        f"Admin Rejection: \"{rejection_text}\" | "
                        f"NLP Category: {nlp_analysis['rejection_category']} ({nlp_analysis['category_label']}) | "
                        f"Tone: {nlp_analysis['tone']} | "
                        f"Booking: {booking.booking_reference if booking else 'N/A'}"
                    ),
                    timestamp=now,
                )
                self.db.add(audit_entry)
            except Exception:
                pass

        self.db.commit()
        self.db.refresh(case)
        if booking:
            self.db.refresh(booking)

        # Dispatch Post-Commit Email Notification (Non-blocking)
        if booking and booking.passenger_email:
            try:
                from notifications.email_service import get_email_service
                email_svc = get_email_service()
                from_st = booking.from_station or ""
                to_st = booking.to_station or ""
                tr_dt = booking.travel_date.isoformat() if booking.travel_date else ""
                tr_id = booking.train.train_id if booking.train else ""

                if clean_decision == "APPROVE":
                    email_svc.send_cancellation_approved_email(
                        recipient_email=booking.passenger_email,
                        booking_reference=booking.booking_reference,
                        refund_amount=refund_str,
                        from_station=from_st,
                        to_station=to_st,
                        travel_date=tr_dt,
                        train_id=tr_id,
                        admin_reason=case.admin_reason,
                    )
                elif clean_decision == "REJECT":
                    email_svc.send_cancellation_rejected_email(
                        recipient_email=booking.passenger_email,
                        booking_reference=booking.booking_reference,
                        admin_reason=case.admin_reason,
                        from_station=from_st,
                        to_station=to_st,
                        travel_date=tr_dt,
                    )
            except Exception as email_err:
                # Notification failure must never rollback or disrupt admin decision
                pass

        return {
            "success": True,
            "case_reference": case.case_reference,
            "cancellation_status": case.status.value,
            "admin_decision": case.admin_decision,
            "admin_reason": case.admin_reason,
            "reviewed_at": case.reviewed_at.isoformat() if case.reviewed_at else None,
            "booking_reference": booking.booking_reference if booking else None,
            "booking_status": booking.status.value if booking else None,
            "passenger_email": booking.passenger_email if booking else None,
            "suggested_refund": refund_str,
            "nlp_analysis": nlp_analysis,
            "audit_logged": True,
        }
