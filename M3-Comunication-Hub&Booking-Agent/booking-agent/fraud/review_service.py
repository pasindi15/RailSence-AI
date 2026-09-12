"""
fraud/review_service.py
-----------------------
RailSense AI — Human-in-the-Loop Fraud Adjudication Service.

Responsibilities:
1. List pending, approved, and rejected fraud review cases for the Admin Console.
2. Review Adjudication:
   - APPROVE:
     * Re-checks train active status.
     * Re-checks schedule existence.
     * Re-checks duplicate active ticket for all passenger NICs.
     * Re-checks cross-train conflicting active journeys.
     * Re-checks seat availability (if seats were consumed while pending, fails with 409).
     * Creates and confirms Booking (status: CONFIRMED).
     * Creates/links Passenger identities and BookingPassenger records.
     * Dispatches confirmation email.
     * Transitions FraudReview.status -> APPROVED.
   - REJECT:
     * Transitions FraudReview.status -> REJECTED.
     * Records admin reason and timestamp.
     * NEVER issues a confirmed ticket.
"""

from __future__ import annotations

import json
import secrets
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from database.models import (
    Booking,
    BookingPassenger,
    BookingStatus,
    FraudReview,
    FraudReviewStatus,
    Passenger,
    Train,
    TrainSchedule,
)
from booking.availability import check_seat_availability, get_schedule_for_trip, get_train_by_public_id, normalize_seat_class
from booking.create_booking import generate_booking_reference
from booking.exceptions import BookingError, ScheduleNotFoundError, SeatsUnavailableError, TrainNotFoundError
from fraud.rules import check_conflicting_active_journey, check_duplicate_active_ticket


class FraudReviewError(BookingError):
    """Base exception for fraud review operations."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class FraudCaseNotFoundError(FraudReviewError):
    def __init__(self, case_ref: str):
        super().__init__(f"Fraud review case '{case_ref}' does not exist.", status_code=404)


class FraudCaseAlreadyAdjudicatedError(FraudReviewError):
    def __init__(self, case_ref: str, current_status: str):
        super().__init__(
            f"Fraud review case '{case_ref}' has already been adjudicated as {current_status}.",
            status_code=409,
        )


class FraudReviewService:
    """Manages administrative adjudication of flagged bookings."""

    def __init__(self, db: Session):
        self.db = db

    def create_review_case(
        self,
        primary_nic: str,
        train_id: str,
        from_station: str,
        to_station: str,
        travel_date: date,
        seat_class: str,
        passenger_count: int,
        risk_score: float = 0.5,
        risk_level: str = "MEDIUM",
        reasons: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        passenger_email: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Create a new FraudReview case with status PENDING_REVIEW."""
        from shared.nic import hash_nic, mask_nic
        case_ref = f"FR-{secrets.randbelow(90000) + 10000}"
        nic_h = hash_nic(primary_nic)
        nic_m = mask_nic(primary_nic)

        b_payload = dict(payload) if payload else {}
        b_payload.setdefault("train_id", train_id)
        b_payload.setdefault("from_station", from_station)
        b_payload.setdefault("to_station", to_station)
        b_payload.setdefault("travel_date", travel_date.isoformat() if hasattr(travel_date, "isoformat") else str(travel_date))
        b_payload.setdefault("seat_class", seat_class)
        b_payload.setdefault("passenger_count", passenger_count)
        b_payload.setdefault("passenger_email", passenger_email)
        b_payload.setdefault("user_id", user_id or "guest")

        review = FraudReview(
            case_reference=case_ref,
            request_reference=None,
            booking_payload=json.dumps(b_payload),
            primary_nic_hash=nic_h,
            risk_score=Decimal(str(round(risk_score, 4))),
            risk_level=risk_level,
            recommended_action="REVIEW" if risk_level == "MEDIUM" else "BLOCK",
            reasons=json.dumps(reasons or ["SECURITY_REVIEW_REQUIRED"]),
            status=FraudReviewStatus.PENDING_REVIEW,
        )
        self.db.add(review)
        self.db.commit()
        return case_ref

    def list_cases(self, status_filter: str | None = None) -> list[dict[str, Any]]:
        """List fraud review cases, optionally filtered by status."""
        query = self.db.query(FraudReview).order_by(FraudReview.created_at.desc())
        if status_filter and status_filter.upper() != "ALL":
            query = query.filter(FraudReview.status == status_filter.upper())

        cases = query.all()
        results = []
        for c in cases:
            try:
                payload = json.loads(c.booking_payload)
            except Exception:
                payload = {}

            try:
                reasons_list = json.loads(c.reasons) if isinstance(c.reasons, str) else c.reasons
            except Exception:
                reasons_list = [c.reasons] if c.reasons else []

            results.append({
                "id": c.id,
                "case_reference": c.case_reference,
                "request_reference": c.request_reference,
                "risk_score": float(c.risk_score),
                "risk_level": c.risk_level,
                "recommended_action": c.recommended_action,
                "reasons": reasons_list,
                "status": c.status.value if hasattr(c.status, "value") else str(c.status),
                "admin_decision": c.admin_decision,
                "admin_reason": c.admin_reason,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
                "booking_details": payload,
            })
        return results

    def review_case(
        self,
        case_reference: str,
        decision: str,
        admin_reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Adjudicate a fraud review case (APPROVE or REJECT).
        """
        case = (
            self.db.query(FraudReview)
            .filter(FraudReview.case_reference == case_reference)
            .first()
        )
        if not case:
            raise FraudCaseNotFoundError(case_reference)

        current_status = case.status.value if hasattr(case.status, "value") else str(case.status)
        if current_status != FraudReviewStatus.PENDING_REVIEW.value:
            raise FraudCaseAlreadyAdjudicatedError(case_reference, current_status)

        norm_decision = decision.strip().upper()
        if norm_decision not in ("APPROVE", "REJECT"):
            raise FraudReviewError("Invalid decision. Must be 'APPROVE' or 'REJECT'.", status_code=400)

        now = datetime.now(timezone.utc)

        # -------------------------------------------------------------------
        # REJECT Branch: No ticket is created
        # -------------------------------------------------------------------
        if norm_decision == "REJECT":
            case.status = FraudReviewStatus.REJECTED
            case.admin_decision = "REJECT"
            case.admin_reason = admin_reason or "Rejected by railway security administration."
            case.reviewed_at = now
            self.db.commit()
            return {
                "success": True,
                "case_reference": case.case_reference,
                "status": "REJECTED",
                "admin_reason": case.admin_reason,
            }

        # -------------------------------------------------------------------
        # APPROVE Branch: Strict Re-verification of Availability & Conflicts
        # -------------------------------------------------------------------
        try:
            payload = json.loads(case.booking_payload)
        except Exception as exc:
            raise FraudReviewError(f"Failed to parse booking payload: {exc}", status_code=500)

        from_station = payload["from_station"]
        to_station = payload["to_station"]
        travel_date = date.fromisoformat(payload["travel_date"])
        train_id = payload["train_id"]
        seat_class = normalize_seat_class(payload["seat_class"])
        passenger_count = payload["passenger_count"]
        passenger_email = payload.get("passenger_email")
        user_id = payload.get("user_id", "guest_passenger")
        fare = Decimal(str(payload.get("fare", "0.00")))
        passengers_data = payload.get("passengers", [])

        # 1. Re-verify train active
        train = get_train_by_public_id(self.db, train_id)

        # 2. Re-verify schedule exists
        schedule = get_schedule_for_trip(
            self.db,
            train_id=train_id,
            from_station=from_station,
            to_station=to_station,
            travel_date=travel_date,
        )

        # 3. Re-verify duplicate active tickets for all passenger NICs
        nic_hashes = [p["nic_hash"] for p in passengers_data if "nic_hash" in p]
        check_duplicate_active_ticket(
            db=self.db,
            nic_hashes=nic_hashes,
            train_id=train.id,
            travel_date=travel_date,
            train_name=train.train_name,
        )

        # 4. Re-verify cross-train time conflicts for all passenger NICs
        check_conflicting_active_journey(
            db=self.db,
            nic_hashes=nic_hashes,
            travel_date=travel_date,
            requested_departure=schedule.departure_time,
            requested_arrival=schedule.arrival_time,
        )

        # 5. Re-verify seat availability (critical: seats may have been booked while pending)
        check_seat_availability(
            db=self.db,
            schedule=schedule,
            seat_class=seat_class,
            requested_seats=passenger_count,
        )

        # 6. Generate booking reference & persist confirmed booking
        booking_ref = generate_booking_reference()
        booking = Booking(
            booking_reference=booking_ref,
            user_id=user_id,
            train_id=train.id,
            schedule_id=schedule.id,
            from_station=from_station,
            to_station=to_station,
            travel_date=travel_date,
            seat_class=seat_class,
            passenger_count=passenger_count,
            passenger_email=passenger_email,
            fare=fare,
            status=BookingStatus.CONFIRMED,
        )
        self.db.add(booking)
        self.db.flush()

        # 7. Create/link passengers and association records
        for p_info in passengers_data:
            p_hash = p_info["nic_hash"]
            p_masked = p_info["nic_masked"]
            p_name = p_info.get("name")

            passenger = self.db.query(Passenger).filter(Passenger.nic_hash == p_hash).first()
            if not passenger:
                passenger = Passenger(
                    nic_hash=p_hash,
                    nic_masked=p_masked,
                    full_name=p_name,
                )
                self.db.add(passenger)
                self.db.flush()

            bp = BookingPassenger(
                booking_id=booking.id,
                passenger_id=passenger.id,
            )
            self.db.add(bp)

        # 8. Update FraudReview status to APPROVED
        case.status = FraudReviewStatus.APPROVED
        case.admin_decision = "APPROVE"
        case.admin_reason = admin_reason or "Approved after administrative verification."
        case.reviewed_at = now

        self.db.commit()
        self.db.refresh(booking)

        # 9. Dispatch confirmation email (non-blocking)
        try:
            from notifications.email_service import get_email_service
            email_svc = get_email_service()
            fare_str = f"{booking.fare:.2f}"
            email_svc.send_booking_confirmation_email(
                recipient_email=booking.passenger_email,
                booking_reference=booking.booking_reference,
                from_station=booking.from_station,
                to_station=booking.to_station,
                travel_date=booking.travel_date.isoformat(),
                train_id=train.train_id,
                seat_class=booking.seat_class,
                passenger_count=booking.passenger_count,
                fare=fare_str,
                status="CONFIRMED",
            )
        except Exception:
            pass

        return {
            "success": True,
            "case_reference": case.case_reference,
            "status": "APPROVED",
            "booking_reference": booking.booking_reference,
            "booking": {
                "booking_reference": booking.booking_reference,
                "from_station": booking.from_station,
                "to_station": booking.to_station,
                "travel_date": booking.travel_date.isoformat(),
                "train_id": train.train_id,
                "seat_class": booking.seat_class,
                "passenger_count": booking.passenger_count,
                "fare": f"{booking.fare:.2f}",
                "status": "CONFIRMED",
            },
        }
