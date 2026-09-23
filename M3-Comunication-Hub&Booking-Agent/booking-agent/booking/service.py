"""
booking/service.py
------------------
Main orchestrator service for the Booking Agent workflow.

Responsibilities (Phase 3):
Orchestrates the deterministic booking pipeline:
1. Validate booking details (BookingRequest)
2. Find train / schedule (availability.get_schedule_for_trip)
3. Check seat availability (availability.check_seat_availability)
4. Calculate fare deterministically (fare.calculate_fare) [upcoming]
5. Generate reference and persist reservation (create_booking.persist_booking) [upcoming]
6. Return structured confirmation (BookingResult) [upcoming]

Architectural & Concurrency rules:
- No LLM involvement in booking availability, seat queries, fare calculation, or booking references.
- Dynamic derived availability: capacity minus sum(CONFIRMED bookings).
- Concurrency: When implementing full reservation persistence in step 5, seat checking
  and booking persistence should execute within the same database transaction.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from .availability import (
    check_seat_availability,
    get_available_seats,
    get_schedule_for_trip,
    get_train_by_public_id,
    validate_booking_details,
)
from .create_booking import generate_booking_reference, persist_booking
from .fare import FareBreakdown, calculate_fare
from schemas.booking import BookingResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from database.models import Train, TrainSchedule
    from schemas.booking import BookingRequest


class BookingService:
    """Orchestrates end-to-end booking reservation operations."""

    def __init__(self, db: Session):
        self.db = db

    def validate_request(self, request: BookingRequest) -> None:
        """
        Validate business rules for a booking request.

        Raises
        ------
        InvalidBookingError: If business validation rules fail.
        """
        validate_booking_details(request)

    def find_train(self, train_id: str) -> Train:
        """
        Look up an active train by its public train_id.

        Raises
        ------
        TrainNotFoundError: If the train is not found or is inactive.
        """
        return get_train_by_public_id(self.db, train_id)

    def find_schedule(
        self,
        train_id: str,
        from_station: str,
        to_station: str,
        travel_date: date,
    ) -> TrainSchedule:
        """
        Look up a matching schedule for a train, route, and travel date.

        Raises
        ------
        TrainNotFoundError: If train does not exist or is inactive.
        ScheduleNotFoundError: If no matching schedule exists.
        """
        return get_schedule_for_trip(
            self.db,
            train_id=train_id,
            from_station=from_station,
            to_station=to_station,
            travel_date=travel_date,
        )

    def check_availability(
        self,
        schedule: TrainSchedule | int,
        seat_class: str,
        passenger_count: int,
    ) -> int:
        """
        Verify seat availability on the schedule for the requested class.

        Returns
        -------
        int: Remaining available seats.

        Raises
        ------
        SeatsUnavailableError: If available_seats < passenger_count.
        """
        return check_seat_availability(
            self.db,
            schedule=schedule,
            seat_class=seat_class,
            requested_seats=passenger_count,
        )

    def get_remaining_seats(
        self,
        schedule: TrainSchedule,
        seat_class: str,
    ) -> int:
        """Calculate remaining available seats for a schedule and class."""
        return get_available_seats(self.db, schedule=schedule, seat_class=seat_class)

    def compute_fare(
        self,
        from_station: str,
        to_station: str,
        seat_class: str,
        passenger_count: int,
        schedule: TrainSchedule | None = None,
    ) -> FareBreakdown:
        """
        Calculate deterministic fare for the given route, class, and passenger count.

        Raises
        ------
        FareNotFoundError: If no matching fare rule exists.
        InvalidBookingError: If parameters are invalid.
        """
        return calculate_fare(
            from_station=from_station,
            to_station=to_station,
            seat_class=seat_class,
            passenger_count=passenger_count,
            schedule=schedule,
            db=self.db,
        )

    def process_booking(
        self, request: BookingRequest, user_id: str | None = None
    ) -> BookingResult:
        """
        Execute the complete deterministic booking workflow with NIC checks & Security ML:
        validate booking details & NICs
        → verify no duplicate NIC in request
        → find active train & matching schedule
        → verify no same-journey duplicate active tickets (Hard Rule 2)
        → verify no cross-train overlapping time conflicts (Hard Rule 3)
        → check seats availability
        → calculate deterministic fare
        → compute behavioral features
        → evaluate risk via Security & Fraud Agent (IsolationForest ML)
        → LOW: persist confirmed booking & dispatch confirmation email
        → MEDIUM / HIGH: create FraudReview (PENDING_REVIEW) & require human adjudication
        """
        import json
        import secrets
        from decimal import Decimal
        from shared.nic import hash_nic, mask_nic
        from fraud.rules import (
            check_conflicting_active_journey,
            check_duplicate_active_ticket,
            check_duplicate_nic_in_booking,
            compute_passenger_fraud_features,
        )
        from fraud.client import request_fraud_score
        from database.models import (
            FraudReview,
            FraudReviewStatus,
            HoldStatus,
            IdempotencyRecord,
            IdempotencyStatus,
            SeatHold,
            TrainSchedule,
        )
        from datetime import datetime, timezone
        import hashlib

        # 0. Idempotency Check
        req_hash = None
        if request.idempotency_key:
            payload_repr = {
                "train_id": request.train_id,
                "from_station": request.from_station.strip(),
                "to_station": request.to_station.strip(),
                "travel_date": request.travel_date.isoformat(),
                "seat_class": request.seat_class,
                "passenger_count": request.passenger_count,
                "passenger_email": str(request.passenger_email).strip() if request.passenger_email else None,
                "passengers": [{"nic": p.nic, "name": p.name} for p in (request.passengers or [])],
            }
            if getattr(request, "schedule_id", None) is not None:
                payload_repr["schedule_id"] = request.schedule_id

            req_hash = hashlib.sha256(json.dumps(payload_repr, sort_keys=True).encode("utf-8")).hexdigest()
            existing_rec = (
                self.db.query(IdempotencyRecord)
                .filter(IdempotencyRecord.idempotency_key == request.idempotency_key)
                .first()
            )
            if existing_rec:
                curr_hash = getattr(existing_rec, "payload_hash", None) or getattr(existing_rec, "request_hash", None)
                if curr_hash != req_hash:
                    from booking.exceptions import IdempotencyConflictError
                    raise IdempotencyConflictError(request.idempotency_key)
                if existing_rec.status in (IdempotencyStatus.COMPLETED, IdempotencyStatus.CONFIRMED, IdempotencyStatus.COMMITTED, "COMPLETED", "CONFIRMED", "COMMITTED") and existing_rec.response_payload:
                    cached_dict = json.loads(existing_rec.response_payload)
                    return BookingResult(**cached_dict)
                if existing_rec.status in (IdempotencyStatus.PROCESSING, "PROCESSING", "PENDING"):
                    raise ValueError(
                        f"CONCURRENT_MUTATION_IN_PROGRESS: Operation with key '{request.idempotency_key}' is already in progress."
                    )

        # 1. Validate booking details
        self.validate_request(request)

        # 2. Hard Rule 1: Duplicate NIC inside same booking
        if request.passengers:
            check_duplicate_nic_in_booking(request.passengers)

        # 3. Find active train
        train = self.find_train(request.train_id)

        # 4. Find matching schedule (by schedule_id if provided, else route+train+date)
        schedule = None
        if getattr(request, "schedule_id", None):
            sched_by_id = self.db.query(TrainSchedule).filter(TrainSchedule.id == request.schedule_id).first()
            if sched_by_id and sched_by_id.train_id == train.id and sched_by_id.travel_date == request.travel_date:
                schedule = sched_by_id

        if not schedule:
            schedule = self.find_schedule(
                train_id=request.train_id,
                from_station=request.from_station,
                to_station=request.to_station,
                travel_date=request.travel_date,
            )

        # Check explicitly cancelled status
        sched_status = (getattr(schedule, "service_status", "SCHEDULED") or "SCHEDULED").upper()
        if sched_status == "CANCELLED":
            raise ValueError(f"Train service '{train.train_id}' on {request.travel_date} has been cancelled.")

        # 4b. Validate Seat Hold if provided
        active_hold = None
        if request.hold_token:
            now_utc = datetime.now(timezone.utc)
            active_hold = (
                self.db.query(SeatHold)
                .filter(
                    SeatHold.hold_token == request.hold_token,
                    SeatHold.status == HoldStatus.ACTIVE,
                )
                .first()
            )
            if not active_hold:
                raise ValueError("HOLD_INVALID: Provided seat hold token is invalid or not active.")
            expires_at = active_hold.expires_at
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at and expires_at < now_utc:
                raise ValueError("HOLD_EXPIRED: Provided seat hold has expired.")
            if active_hold.schedule_id != schedule.id:
                raise ValueError("HOLD_SCHEDULE_MISMATCH: Provided hold does not match selected journey schedule.")
            if active_hold.seat_count < request.passenger_count:
                raise ValueError("HOLD_CAPACITY_MISMATCH: Provided hold covers fewer seats than requested.")

        # 5. Deterministic protected identities (HMAC-SHA256 & masking)
        nic_hashes: list[str] = []
        passenger_records: list[dict[str, Any]] = []
        if request.passengers:
            for p in request.passengers:
                h = hash_nic(p.nic)
                m = mask_nic(p.nic)
                nic_hashes.append(h)
                p_dob = getattr(p, "dob", None)
                passenger_records.append({
                    "name": p.name,
                    "nic_hash": h,
                    "nic_masked": m,
                    "dob": p_dob,
                })

        # 6. Hard Rule 2: Same train duplicate ticket check
        check_duplicate_active_ticket(
            db=self.db,
            nic_hashes=nic_hashes,
            train_id=train.id,
            travel_date=request.travel_date,
            train_name=train.train_name,
        )

        # 7. Hard Rule 3: Cross-train overlapping time conflict check (with overnight/timezone support)
        check_conflicting_active_journey(
            db=self.db,
            nic_hashes=nic_hashes,
            travel_date=request.travel_date,
            requested_departure=schedule.departure_time,
            requested_arrival=schedule.arrival_time,
        )

        # 8. Check seat availability (if not holding seats)
        if not active_hold:
            self.check_availability(
                schedule=schedule,
                seat_class=request.seat_class,
                passenger_count=request.passenger_count,
            )

        # 9. Calculate deterministic fare
        fare_breakdown = self.compute_fare(
            from_station=request.from_station,
            to_station=request.to_station,
            seat_class=request.seat_class,
            passenger_count=request.passenger_count,
            schedule=schedule,
        )

        # 10. Behavioral feature generation & Security Agent ML scoring
        features = compute_passenger_fraud_features(
            db=self.db,
            nic_hashes=nic_hashes,
            schedule=schedule,
        )
        primary_nic_key = nic_hashes[0][:16] if nic_hashes else "guest_identity"
        travel_ctx = {
            "train_id": train.train_id,
            "from_station": request.from_station.strip(),
            "to_station": request.to_station.strip(),
            "travel_date": request.travel_date.isoformat(),
            "passenger_count": request.passenger_count,
        }
        risk_result = request_fraud_score(
            features=features,
            nic_key=primary_nic_key,
            travel_context=travel_ctx,
        )
        risk_level = str(risk_result.get("risk_level", "LOW")).upper()
        risk_score = float(risk_result.get("risk_score", 0.0))
        reasons = risk_result.get("reasons", [])
        recommended_action = risk_result.get("recommended_action", "ALLOW")
        grounded_summary = risk_result.get("grounded_summary")

        # 11. Risk Decision Policy:
        # MEDIUM / HIGH -> Flag for human review (no confirmed ticket issued)
        if risk_level in ("MEDIUM", "HIGH"):
            case_ref = f"FR-{secrets.randbelow(90000) + 10000}"
            sanitized_payload = {
                "train_id": train.train_id,
                "from_station": request.from_station.strip(),
                "to_station": request.to_station.strip(),
                "travel_date": request.travel_date.isoformat(),
                "seat_class": request.seat_class,
                "passenger_count": request.passenger_count,
                "passenger_email": str(request.passenger_email).strip() if getattr(request, "passenger_email", None) else None,
                "fare": str(fare_breakdown.total_fare),
                "user_id": user_id or getattr(request, "user_id", None) or "guest_passenger",
                "passengers": passenger_records,
                "hold_token": request.hold_token,
                "grounded_summary": grounded_summary,
            }

            primary_hash = nic_hashes[0] if nic_hashes else primary_nic_key

            fraud_review = FraudReview(
                case_reference=case_ref,
                request_reference=None,
                booking_payload=json.dumps(sanitized_payload),
                primary_nic_hash=primary_hash,
                risk_score=Decimal(str(round(risk_score, 4))),
                risk_level=risk_level,
                recommended_action=recommended_action,
                reasons=json.dumps(reasons),
                status=FraudReviewStatus.PENDING_REVIEW,
            )
            self.db.add(fraud_review)
            self.db.commit()

            result = BookingResult(
                booking_reference=None,
                ticket_token=None,
                train_id=train.train_id,
                from_station=request.from_station.strip(),
                to_station=request.to_station.strip(),
                travel_date=request.travel_date,
                seat_class=request.seat_class,
                passenger_count=request.passenger_count,
                passenger_email=request.passenger_email,
                fare=fare_breakdown.total_fare,
                status="PENDING_FRAUD_REVIEW",
                case_reference=case_ref,
                risk_level=risk_level,
                reasons=reasons,
                hold_token=request.hold_token,
            )

            if request.idempotency_key and req_hash:
                idem_rec = IdempotencyRecord(
                    idempotency_key=request.idempotency_key,
                    user_id=user_id or getattr(request, "user_id", None) or "guest_passenger",
                    operation_type="BOOKING_MUTATION",
                    payload_hash=req_hash,
                    response_payload=result.model_dump_json(),
                    status=IdempotencyStatus.COMPLETED,
                )
                self.db.add(idem_rec)
                self.db.commit()

            return result

        # 12. Normal confirmed booking persistence for LOW risk
        booking_ref = generate_booking_reference()
        try:
            booking = persist_booking(
                db=self.db,
                request=request,
                schedule=schedule,
                booking_reference=booking_ref,
                fare=fare_breakdown.total_fare,
                user_id=user_id,
                passenger_records=passenger_records,
                idempotency_key=request.idempotency_key,
                actor=user_id,
                hold_id=active_hold.id if active_hold else None,
            )
        except Exception:
            self.db.rollback()
            raise

        # 13. Dispatch post-commit email notification (non-blocking)
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
                status=booking.status.value if hasattr(booking.status, "value") else str(booking.status),
            )
        except Exception:
            # Email notification failure must never rollback or disrupt confirmed booking
            pass

        # 14. Return BookingResult
        result = BookingResult(
            booking_reference=booking.booking_reference,
            ticket_token=booking.ticket_token,
            train_id=train.train_id,
            from_station=booking.from_station,
            to_station=booking.to_station,
            travel_date=booking.travel_date,
            seat_class=booking.seat_class,
            passenger_count=booking.passenger_count,
            passenger_email=booking.passenger_email,
            fare=booking.fare,
            status=booking.status.value if hasattr(booking.status, "value") else str(booking.status),
            risk_level="LOW",
            hold_token=request.hold_token,
        )

        if request.idempotency_key and req_hash:
            try:
                existing_rec = (
                    self.db.query(IdempotencyRecord)
                    .filter(IdempotencyRecord.idempotency_key == request.idempotency_key)
                    .first()
                )
                if not existing_rec:
                    idem_rec = IdempotencyRecord(
                        idempotency_key=request.idempotency_key,
                        user_id=user_id or getattr(request, "user_id", None) or "guest_passenger",
                        operation_type="BOOKING_MUTATION",
                        payload_hash=req_hash,
                        response_payload=result.model_dump_json(),
                        status=IdempotencyStatus.COMPLETED,
                    )
                    self.db.add(idem_rec)
                    self.db.commit()
            except Exception:
                pass

        return result
