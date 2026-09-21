"""
admin_chat/retrieval.py
-----------------------
Structured Information Retrieval (IR) layer for the Admin Booking Intelligence Assistant.
Executes parameterized, read-only queries against M3 database tables.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    Booking,
    BookingPassenger,
    BookingStatus,
    CancellationRequest,
    CancellationStatus,
    FraudReview,
    FraudReviewStatus,
    HoldStatus,
    Passenger,
    SeatHold,
    Train,
    TrainSchedule,
)
from booking.availability import (
    get_available_seats,
    get_booked_seats,
    get_schedules_for_route,
    get_train_by_public_id,
    normalize_seat_class,
)
from shared.nic import mask_nic
from .date_parser import get_current_colombo_date


def _resolve_train(db: Session, train_name: str | None, train_id: str | None) -> Train | None:
    """Find a Train ORM entity by train_id or train_name."""
    if train_id:
        clean_tid = train_id.strip().upper()
        # Direct train_id match
        t = db.query(Train).filter(Train.train_id == clean_tid).first()
        if t:
            return t
        # Match numeric suffix (e.g. '1005' in '1005' or 'PM-4082' in '4082')
        t = db.query(Train).filter(Train.train_id.ilike(f"%{clean_tid}%")).first()
        if t:
            return t

    if train_name:
        clean_name = train_name.strip()
        t = db.query(Train).filter(func.lower(Train.train_name) == clean_name.lower()).first()
        if t:
            return t
        t = db.query(Train).filter(Train.train_name.ilike(f"%{clean_name}%")).first()
        if t:
            return t

    return None


def retrieve_seat_availability(db: Session, entities: dict[str, Any]) -> dict[str, Any]:
    """
    Retrieve live seat availability, capacity, confirmed bookings, and active holds.
    """
    travel_date_str = entities.get("travel_date")
    parsed_date = date.fromisoformat(travel_date_str) if travel_date_str else get_current_colombo_date()
    target_class = entities.get("seat_class")
    threshold_op = entities.get("seat_threshold_op")
    threshold_val = entities.get("seat_threshold_val")

    train_name = entities.get("train_name")
    train_id = entities.get("train_id")
    train = _resolve_train(db, train_name, train_id)

    # 1. Single Train Query
    if train:
        schedules = (
            db.query(TrainSchedule)
            .filter(
                TrainSchedule.train_id == train.id,
                TrainSchedule.travel_date == parsed_date,
            )
            .all()
        )

        # If missing, ensure journeys from catalog
        if not schedules:
            from booking.availability import ensure_journeys_for_date
            try:
                ensure_journeys_for_date(db, parsed_date, train_id=train.train_id)
                schedules = (
                    db.query(TrainSchedule)
                    .filter(
                        TrainSchedule.train_id == train.id,
                        TrainSchedule.travel_date == parsed_date,
                    )
                    .all()
                )
            except Exception:
                pass

        if not schedules:
            return {
                "found": False,
                "train_name": train.train_name,
                "train_id": train.train_id,
                "travel_date": parsed_date.isoformat(),
                "message": f"No active schedule found for {train.train_name} (#{train.train_id}) on {parsed_date.isoformat()}.",
                "records": [],
            }

        records = []
        for s in schedules:
            classes_to_check = [target_class] if target_class else ["First Class", "Second Class"]
            for cname in classes_to_check:
                try:
                    canonical = normalize_seat_class(cname)
                except Exception:
                    continue

                capacity = s.first_class_capacity if canonical == "First Class" else s.second_class_capacity
                booked = get_booked_seats(db, schedule_id=s.id, seat_class=canonical)
                available = get_available_seats(db, schedule=s, seat_class=canonical)

                # Get active holds specifically
                try:
                    from booking.lifecycle import get_active_hold_seat_count
                    held = get_active_hold_seat_count(db, schedule_id=s.id, seat_class=canonical)
                except Exception:
                    held = 0

                confirmed = max(0, booked - held)

                records.append({
                    "schedule_id": s.id,
                    "train_id": train.train_id,
                    "train_name": train.train_name,
                    "from_station": s.from_station,
                    "to_station": s.to_station,
                    "departure_time": s.departure_time.strftime("%H:%M") if s.departure_time else "",
                    "arrival_time": s.arrival_time.strftime("%H:%M") if s.arrival_time else "",
                    "travel_date": s.travel_date.isoformat(),
                    "seat_class": canonical,
                    "capacity": capacity,
                    "confirmed": confirmed,
                    "held": held,
                    "available": available,
                })

        return {
            "found": True,
            "train_name": train.train_name,
            "train_id": train.train_id,
            "travel_date": parsed_date.isoformat(),
            "records": records,
        }

    # 2. General / Threshold Query (e.g. "Which trains have less than 10 seats?")
    active_schedules = (
        db.query(TrainSchedule, Train)
        .join(Train, TrainSchedule.train_id == Train.id)
        .filter(
            Train.active == True,  # noqa: E712
            TrainSchedule.travel_date == parsed_date,
        )
        .all()
    )

    records = []
    for s, t in active_schedules:
        for cname in ["First Class", "Second Class"]:
            avail = get_available_seats(db, schedule=s, seat_class=cname)
            if threshold_op == "<" and threshold_val is not None:
                if avail >= threshold_val:
                    continue
            records.append({
                "schedule_id": s.id,
                "train_id": t.train_id,
                "train_name": t.train_name,
                "seat_class": cname,
                "available": avail,
                "from_station": s.from_station,
                "to_station": s.to_station,
            })

    return {
        "found": len(records) > 0,
        "travel_date": parsed_date.isoformat(),
        "seat_class": target_class,
        "records": records[:10],
    }


def retrieve_fraud_reviews(db: Session, entities: dict[str, Any]) -> dict[str, Any]:
    """
    Retrieve fraud review records available to M3.
    """
    case_ref = entities.get("case_reference")
    bkg_ref = entities.get("booking_reference")
    risk_level = entities.get("risk_level")
    review_status = entities.get("review_status", "PENDING")
    is_count = entities.get("is_count_request", False)

    # 1. Lookup specific case by reference
    if case_ref:
        case = db.query(FraudReview).filter(FraudReview.case_reference.ilike(f"%{case_ref.strip()}%")).first()
        if case:
            payload = json.loads(case.booking_payload) if case.booking_payload else {}
            return {
                "type": "single_case",
                "case_reference": case.case_reference,
                "risk_score": float(case.risk_score),
                "risk_level": case.risk_level,
                "status": case.status.value if hasattr(case.status, "value") else str(case.status),
                "reasons": json.loads(case.reasons) if case.reasons.startswith("[") else [case.reasons],
                "admin_decision": case.admin_decision,
                "admin_reason": case.admin_reason,
                "created_at": case.created_at.isoformat() if case.created_at else None,
                "booking_details": {
                    "train_id": payload.get("train_id"),
                    "from_station": payload.get("from_station"),
                    "to_station": payload.get("to_station"),
                    "travel_date": payload.get("travel_date"),
                    "passenger_count": payload.get("passenger_count"),
                },
            }

    # 2. Lookup by booking reference
    if bkg_ref:
        bkg_clean = bkg_ref.strip().upper()
        # Find if booking payload contains this reference or case reference
        all_cases = db.query(FraudReview).all()
        for c in all_cases:
            if bkg_clean in (c.case_reference or "") or bkg_clean in (c.booking_payload or ""):
                payload = json.loads(c.booking_payload) if c.booking_payload else {}
                return {
                    "type": "single_case",
                    "case_reference": c.case_reference,
                    "risk_score": float(c.risk_score),
                    "risk_level": c.risk_level,
                    "status": c.status.value if hasattr(c.status, "value") else str(c.status),
                    "reasons": json.loads(c.reasons) if c.reasons.startswith("[") else [c.reasons],
                    "admin_decision": c.admin_decision,
                    "admin_reason": c.admin_reason,
                    "booking_details": {
                        "booking_reference": bkg_clean,
                        "train_id": payload.get("train_id"),
                        "travel_date": payload.get("travel_date"),
                    },
                }

    # 3. Query queue / aggregates
    query = db.query(FraudReview)
    if risk_level:
        query = query.filter(FraudReview.risk_level == risk_level.upper())
    if review_status:
        st_enum = FraudReviewStatus.PENDING_REVIEW if review_status.upper() == "PENDING" else review_status.upper()
        query = query.filter(FraudReview.status == st_enum)

    total_count = query.count()

    if is_count:
        return {
            "type": "count",
            "count": total_count,
            "risk_level": risk_level,
            "review_status": review_status,
        }

    cases = query.order_by(FraudReview.created_at.desc()).limit(8).all()
    results = []
    for c in cases:
        payload = json.loads(c.booking_payload) if c.booking_payload else {}
        reasons_list = json.loads(c.reasons) if c.reasons.startswith("[") else [c.reasons]
        results.append({
            "case_reference": c.case_reference,
            "risk_score": float(c.risk_score),
            "risk_level": c.risk_level,
            "reasons": reasons_list,
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
            "train_id": payload.get("train_id"),
            "travel_date": payload.get("travel_date"),
        })

    return {
        "type": "list",
        "count": total_count,
        "cases": results,
        "risk_level": risk_level,
        "review_status": review_status,
    }


def retrieve_cancellations(db: Session, entities: dict[str, Any]) -> dict[str, Any]:
    """
    Retrieve cancellation requests and refund evaluations.
    """
    case_ref = entities.get("case_reference")
    bkg_ref = entities.get("booking_reference")
    review_status = entities.get("review_status", "PENDING")
    is_count = entities.get("is_count_request", False)

    # 1. Specific Case Lookup
    if case_ref:
        cr = db.query(CancellationRequest).filter(CancellationRequest.case_reference.ilike(f"%{case_ref.strip()}%")).first()
        if cr:
            b = cr.booking
            return {
                "type": "single_case",
                "case_reference": cr.case_reference,
                "booking_reference": b.booking_reference if b else None,
                "reason": cr.reason,
                "reason_category": cr.reason_category,
                "eligibility": cr.eligibility,
                "suggested_refund": f"{cr.suggested_refund:.2f}" if cr.suggested_refund else "0.00",
                "status": cr.status.value if hasattr(cr.status, "value") else str(cr.status),
                "admin_decision": cr.admin_decision,
                "admin_reason": cr.admin_reason,
            }

    # 2. Specific Booking Reference Lookup
    if bkg_ref:
        bkg = db.query(Booking).filter(Booking.booking_reference == bkg_ref.strip().upper()).first()
        if bkg and bkg.cancellation_request:
            cr = bkg.cancellation_request
            return {
                "type": "single_case",
                "case_reference": cr.case_reference,
                "booking_reference": bkg.booking_reference,
                "gross_fare": f"{bkg.fare:.2f}",
                "reason": cr.reason,
                "reason_category": cr.reason_category,
                "eligibility": cr.eligibility,
                "suggested_refund": f"{cr.suggested_refund:.2f}" if cr.suggested_refund else "0.00",
                "status": cr.status.value if hasattr(cr.status, "value") else str(cr.status),
                "admin_decision": cr.admin_decision,
                "admin_reason": cr.admin_reason,
            }

    # 3. Queue / Aggregate Query
    query = db.query(CancellationRequest)
    if review_status:
        st_enum = CancellationStatus.PENDING_ADMIN_REVIEW if review_status.upper() == "PENDING" else review_status.upper()
        query = query.filter(CancellationRequest.status == st_enum)

    total_count = query.count()

    if is_count:
        return {
            "type": "count",
            "count": total_count,
            "review_status": review_status,
        }

    cases = query.order_by(CancellationRequest.created_at.desc()).limit(8).all()
    results = []
    for c in cases:
        b = c.booking
        results.append({
            "case_reference": c.case_reference,
            "booking_reference": b.booking_reference if b else "N/A",
            "reason": c.reason,
            "suggested_refund": f"{c.suggested_refund:.2f}" if c.suggested_refund else "0.00",
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
        })

    return {
        "type": "list",
        "count": total_count,
        "cases": results,
        "review_status": review_status,
    }


def retrieve_manifest(db: Session, entities: dict[str, Any]) -> dict[str, Any]:
    """
    Retrieve passenger bookings and manifest data (strictly with masked NICs).
    """
    travel_date_str = entities.get("travel_date")
    parsed_date = date.fromisoformat(travel_date_str) if travel_date_str else get_current_colombo_date()
    train_name = entities.get("train_name")
    train_id = entities.get("train_id")
    target_class = entities.get("seat_class")
    is_count = entities.get("is_count_request", False)

    train = _resolve_train(db, train_name, train_id)

    query = (
        db.query(Booking)
        .join(Train, Booking.train_id == Train.id)
        .join(TrainSchedule, Booking.schedule_id == TrainSchedule.id)
    )

    if train:
        query = query.filter(Booking.train_id == train.id)
    if parsed_date:
        query = query.filter(Booking.travel_date == parsed_date)
    if target_class:
        query = query.filter(func.lower(func.trim(Booking.seat_class)) == target_class.lower())

    # Default to confirmed bookings for manifests unless requested otherwise
    query = query.filter(Booking.status == BookingStatus.CONFIRMED)

    total_bookings = query.count()
    total_passengers = db.query(func.coalesce(func.sum(Booking.passenger_count), 0)).filter(
        Booking.id.in_(query.with_entities(Booking.id))
    ).scalar() or 0

    if is_count:
        return {
            "type": "count",
            "train_name": train.train_name if train else "All Trains",
            "travel_date": parsed_date.isoformat(),
            "seat_class": target_class,
            "total_bookings": total_bookings,
            "total_passengers": int(total_passengers),
        }

    bookings = query.order_by(Booking.created_at.desc()).limit(15).all()
    results = []
    for b in bookings:
        passengers_info = []
        for bp in b.booking_passengers:
            p = bp.passenger
            if p:
                passengers_info.append({
                    "full_name": p.full_name or "Passenger",
                    "nic_masked": p.nic_masked,
                })

        results.append({
            "booking_reference": b.booking_reference,
            "train_name": b.train.train_name if b.train else "",
            "from_station": b.from_station,
            "to_station": b.to_station,
            "travel_date": b.travel_date.isoformat(),
            "seat_class": b.seat_class,
            "passenger_count": b.passenger_count,
            "passengers": passengers_info,
            "fare": f"{b.fare:.2f}",
            "status": b.status.value if hasattr(b.status, "value") else str(b.status),
        })

    return {
        "type": "manifest",
        "train_name": train.train_name if train else "All Trains",
        "travel_date": parsed_date.isoformat(),
        "total_bookings": total_bookings,
        "total_passengers": int(total_passengers),
        "bookings": results,
    }


def retrieve_booking_lookup(db: Session, booking_ref: str) -> dict[str, Any]:
    """
    Deep timeline inspection of a single booking ("What happened to BKG-30321?").
    """
    clean_ref = booking_ref.strip().upper()
    booking = db.query(Booking).filter(Booking.booking_reference == clean_ref).first()
    if not booking:
        # Try substring match
        booking = db.query(Booking).filter(Booking.booking_reference.ilike(f"%{clean_ref}%")).first()

    if not booking:
        return {"found": False, "booking_reference": clean_ref}

    canc = booking.cancellation_request
    status_str = booking.status.value if hasattr(booking.status, "value") else str(booking.status)

    passengers_info = []
    for bp in booking.booking_passengers:
        p = bp.passenger
        if p:
            passengers_info.append({
                "full_name": p.full_name or "Passenger",
                "nic_masked": p.nic_masked,
            })

    return {
        "found": True,
        "booking_reference": booking.booking_reference,
        "train_id": booking.train.train_id if booking.train else "",
        "train_name": booking.train.train_name if booking.train else "",
        "route": f"{booking.from_station} → {booking.to_station}",
        "travel_date": booking.travel_date.isoformat(),
        "seat_class": booking.seat_class,
        "passenger_count": booking.passenger_count,
        "passengers": passengers_info,
        "fare": f"{booking.fare:.2f}",
        "status": status_str,
        "created_at": booking.created_at.strftime("%d %b %Y %H:%M") if booking.created_at else None,
        "cancellation": {
            "case_reference": canc.case_reference,
            "status": canc.status.value if hasattr(canc.status, "value") else str(canc.status),
            "suggested_refund": f"{canc.suggested_refund:.2f}" if canc.suggested_refund else None,
            "reason": canc.reason,
            "admin_decision": canc.admin_decision,
        } if canc else None,
    }


def retrieve_booking_summary(db: Session, entities: dict[str, Any]) -> dict[str, Any]:
    """
    Compile high-level administrative KPI summary for the current day.
    """
    today = get_current_colombo_date()
    now_utc = datetime.now(timezone.utc)

    # 1. Confirmed bookings & passengers
    confirmed_bookings = db.query(Booking).filter(
        Booking.status == BookingStatus.CONFIRMED,
        func.date(Booking.created_at) == today,
    ).count()

    passenger_count = db.query(func.coalesce(func.sum(Booking.passenger_count), 0)).filter(
        Booking.status == BookingStatus.CONFIRMED,
        func.date(Booking.created_at) == today,
    ).scalar() or 0

    # 2. Pending cancellations
    pending_cancellations = db.query(CancellationRequest).filter(
        CancellationRequest.status == CancellationStatus.PENDING_ADMIN_REVIEW
    ).count()

    # 3. Pending fraud reviews
    pending_fraud = db.query(FraudReview).filter(
        FraudReview.status == FraudReviewStatus.PENDING_REVIEW
    ).count()

    # 4. Active seat holds
    active_holds = db.query(SeatHold).filter(
        SeatHold.status == HoldStatus.ACTIVE,
        SeatHold.expires_at > now_utc,
    ).count()

    # 5. Waiting list passengers
    waiting_count = db.query(func.coalesce(func.sum(Booking.passenger_count), 0)).filter(
        Booking.status == BookingStatus.HELD
    ).scalar() or 0

    return {
        "date": today.isoformat(),
        "confirmed_bookings": int(confirmed_bookings),
        "passengers": int(passenger_count),
        "pending_cancellations": int(pending_cancellations),
        "pending_fraud_reviews": int(pending_fraud),
        "active_seat_holds": int(active_holds),
        "waiting_list_passengers": int(waiting_count),
    }
