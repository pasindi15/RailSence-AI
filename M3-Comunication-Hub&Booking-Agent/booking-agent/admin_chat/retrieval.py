"""
admin_chat/retrieval.py
-----------------------
Structured Information Retrieval (IR) layer for the Admin Booking Intelligence Assistant.
Executes parameterized, read-only queries against M3 database tables.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

_CURRENT_DIR = Path(__file__).resolve().parent
_WORKSPACE_ROOT = _CURRENT_DIR.parents[2]
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

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
    stations_match,
)
from shared.nic import mask_nic
from .date_parser import get_current_colombo_date


def retrieve_schedule(db: Session, entities: dict[str, Any]) -> dict[str, Any]:
    """Retrieve deterministic train schedules without treating them as seat queries."""
    travel_date = date.fromisoformat(entities["travel_date"]) if entities.get("travel_date") else get_current_colombo_date()
    train = _resolve_train(db, entities.get("train_name"), entities.get("train_id"))
    if train is None and entities.get("train_name"):
        from booking.services_catalog import DAILY_SERVICES
        wanted = entities["train_name"].lower()
        service = next((s for s in DAILY_SERVICES if wanted in s.train_name.lower()), None)
        if service:
            from booking.availability import ensure_journeys_for_date
            try:
                ensure_journeys_for_date(db, travel_date, train_id=service.train_id)
            except Exception:
                pass
            train = _resolve_train(db, None, service.train_id)

    from_station = entities.get("origin_station")
    to_station = entities.get("destination_station")
    if from_station and to_station:
        from booking.availability import get_schedules_for_route
        options = get_schedules_for_route(db, from_station, to_station, travel_date)
    else:
        query = db.query(TrainSchedule, Train).join(Train, TrainSchedule.train_id == Train.id).filter(
            TrainSchedule.travel_date == travel_date,
            Train.active == True,  # noqa: E712
        )
        if train:
            query = query.filter(Train.id == train.id)
        options = []
        for schedule, row_train in query.order_by(TrainSchedule.departure_time).all():
            options.append({
                "schedule_id": schedule.id,
                "train_id": row_train.train_id,
                "train_name": row_train.train_name,
                "from_station": schedule.from_station,
                "to_station": schedule.to_station,
                "departure_time": schedule.departure_time.strftime("%H:%M") if schedule.departure_time else "",
                "arrival_time": schedule.arrival_time.strftime("%H:%M") if schedule.arrival_time else "",
                "travel_date": schedule.travel_date.isoformat(),
                "service_status": getattr(schedule.service_status, "value", schedule.service_status) or "SCHEDULED",
            })

    return {
        "found": bool(options),
        "travel_date": travel_date.isoformat(),
        "train_name": train.train_name if train else entities.get("train_name"),
        "records": options[:25],
    }


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
    catalog_service = None
    if train_name and not train_id:
        from booking.services_catalog import DAILY_SERVICES
        requested_name = train_name.strip().lower()
        catalog_service = next(
            (
                service for service in DAILY_SERVICES
                if requested_name == service.train_name.lower()
                or requested_name in service.train_name.lower()
            ),
            None,
        )

    # Resolve named daily services through the M3 catalog first. This prevents
    # a stale row with the same public ID but a different display name from
    # answering a Podi Menike question as Udarata Menike (or vice versa).
    if catalog_service:
        from booking.availability import ensure_journeys_for_date
        train = _resolve_train(db, None, catalog_service.train_id)
        if train:
            existing_schedule = db.query(TrainSchedule.id).filter(
                TrainSchedule.train_id == train.id,
                TrainSchedule.travel_date == parsed_date,
            ).first()
        else:
            existing_schedule = None
        if not existing_schedule:
            try:
                ensure_journeys_for_date(db, parsed_date, train_id=catalog_service.train_id)
            except Exception:
                pass
            train = _resolve_train(db, None, catalog_service.train_id)
    else:
        train = _resolve_train(db, train_name, train_id)

    display_train_name = (
        catalog_service.train_name if catalog_service else (train.train_name if train else train_name)
    )
    display_train_id = (
        catalog_service.train_id if catalog_service else (train.train_id if train else train_id)
    )

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
                "train_name": display_train_name,
                "train_id": display_train_id,
                "travel_date": parsed_date.isoformat(),
                "message": f"No active schedule found for {display_train_name} (#{display_train_id}) on {parsed_date.isoformat()}.",
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
                    "train_id": display_train_id,
                    "train_name": display_train_name,
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

        # Deduplicate: Multiple schedule rows can exist for the same train+date+departure_time
        # (e.g. "Colombo" and "Colombo Fort" are two rows for the same physical service).
        # Collapse by (departure_time, seat_class). Keep one internally
        # consistent record, choosing the most conservative availability when
        # duplicate/stale schedules exist for the same physical service.
        seen_dedup: dict[tuple, dict] = {}
        for r in records:
            key = (r["departure_time"], r["seat_class"])
            if key not in seen_dedup:
                seen_dedup[key] = dict(r)
            else:
                prev = seen_dedup[key]
                if r["available"] < prev["available"]:
                    seen_dedup[key] = dict(r)
        records = list(seen_dedup.values())

        return {
            "found": True,
            "train_name": display_train_name,
            "train_id": display_train_id,
            "travel_date": parsed_date.isoformat(),
            "records": records,
        }

    # 2. General / Threshold Query (e.g. "Which trains have less than 10 seats?", "Show available First, Second, and Third Class seats")
    from booking.availability import ensure_journeys_for_date
    try:
        ensure_journeys_for_date(db, parsed_date)
    except Exception:
        pass

    active_schedules = (
        db.query(TrainSchedule, Train)
        .join(Train, TrainSchedule.train_id == Train.id)
        .filter(
            Train.active == True,  # noqa: E712
            TrainSchedule.travel_date == parsed_date,
        )
        .all()
    )

    classes_to_check = entities.get("seat_classes") or ([target_class] if target_class else ["First Class", "Second Class"])
    records = []
    for s, t in active_schedules:
        if entities.get("origin_station") and not stations_match(s.from_station, entities["origin_station"]):
            continue
        if entities.get("destination_station") and not stations_match(s.to_station, entities["destination_station"]):
            continue
        for cname in classes_to_check:
            if cname in ["First Class", "Second Class"]:
                avail = get_available_seats(db, schedule=s, seat_class=cname)
                if threshold_op == "<" and threshold_val is not None:
                    if avail >= threshold_val:
                        continue
                records.append({
                    "schedule_id": s.id,
                    "train_id": t.train_id,
                    "train_name": t.train_name,
                    "seat_class": cname,
                    "capacity": s.first_class_capacity if cname == "First Class" else s.second_class_capacity,
                    "confirmed": max(0, (s.first_class_capacity if cname == "First Class" else s.second_class_capacity) - avail),
                    "held": 0,
                    "available": avail,
                    "from_station": s.from_station,
                    "to_station": s.to_station,
                    "departure_time": s.departure_time.strftime("%H:%M") if s.departure_time else "",
                    "arrival_time": s.arrival_time.strftime("%H:%M") if s.arrival_time else "",
                })

    has_third_class = "Third Class" in classes_to_check or entities.get("all_classes_requested")

    return {
        "found": len(records) > 0,
        "travel_date": parsed_date.isoformat(),
        "seat_class": target_class,
        "seat_classes": classes_to_check,
        "records": records[:12],
        "third_class_note": (
            "Third Class is operated as general unreserved seating on Sri Lanka Railways intercity express trains and is available directly on station platforms without reservation."
            if has_third_class else None
        ),
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
        clean_cr = case_ref.strip().upper()
        case = db.query(FraudReview).filter(FraudReview.case_reference.ilike(f"%{clean_cr}%")).first()
        if not case and "-" in clean_cr:
            num_part = clean_cr.split("-")[-1]
            if len(num_part) >= 3:
                case = db.query(FraudReview).filter(FraudReview.case_reference.ilike(f"%{num_part}%")).first()
        if case:
            payload = json.loads(case.booking_payload) if case.booking_payload else {}
            return {
                "type": "single_case",
                "found": True,
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
        return {
            "type": "single_case",
            "found": False,
            "case_reference": clean_cr,
            "message": f"Fraud review case '{clean_cr}' was not found in the review queue.",
        }

    # 2. Lookup by booking reference
    if bkg_ref:
        bkg_clean = bkg_ref.strip().upper()
        all_cases = db.query(FraudReview).all()
        for c in all_cases:
            if bkg_clean in (c.case_reference or "") or bkg_clean in (c.booking_payload or ""):
                payload = json.loads(c.booking_payload) if c.booking_payload else {}
                return {
                    "type": "single_case",
                    "found": True,
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
        return {
            "type": "single_case",
            "found": False,
            "booking_reference": bkg_clean,
            "message": f"No fraud review record was found for booking reference '{bkg_clean}'.",
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
        clean_cr = case_ref.strip().upper()
        cr = db.query(CancellationRequest).filter(CancellationRequest.case_reference.ilike(f"%{clean_cr}%")).first()
        if not cr and "-" in clean_cr:
            num_part = clean_cr.split("-")[-1]
            if len(num_part) >= 3:
                cr = db.query(CancellationRequest).filter(CancellationRequest.case_reference.ilike(f"%{num_part}%")).first()
        if cr:
            b = cr.booking
            return {
                "type": "single_case",
                "found": True,
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
        return {
            "type": "single_case",
            "found": False,
            "case_reference": clean_cr,
            "message": f"Cancellation request case '{clean_cr}' was not found in the cancellation queue.",
        }

    # 2. Specific Booking Reference Lookup
    if bkg_ref:
        bkg_clean = bkg_ref.strip().upper()
        bkg = db.query(Booking).filter(Booking.booking_reference == bkg_clean).first()
        if bkg and bkg.cancellation_request:
            cr = bkg.cancellation_request
            return {
                "type": "single_case",
                "found": True,
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
        return {
            "type": "single_case",
            "found": False,
            "booking_reference": bkg_clean,
            "message": f"No cancellation request was found for booking reference '{bkg_clean}'.",
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
    has_date_in_query = bool(travel_date_str)

    train_name = entities.get("train_name")
    train_id = entities.get("train_id")
    target_class = entities.get("seat_class")
    is_count = entities.get("is_count_request", False)
    from_station = entities.get("origin_station")
    to_station = entities.get("destination_station")

    train = _resolve_train(db, train_name, train_id)

    query = (
        db.query(Booking)
        .join(Train, Booking.train_id == Train.id)
        .join(TrainSchedule, Booking.schedule_id == TrainSchedule.id)
    )

    if train:
        query = query.filter(Booking.train_id == train.id)
    if from_station:
        query = query.filter(Booking.from_station.ilike(f"%{from_station}%"))
    if to_station:
        query = query.filter(Booking.to_station.ilike(f"%{to_station}%"))
    if has_date_in_query and parsed_date:
        query = query.filter(Booking.travel_date == parsed_date)
    elif parsed_date:
        query = query.filter(Booking.travel_date >= parsed_date)

    if target_class:
        query = query.filter(func.lower(func.trim(Booking.seat_class)) == target_class.lower())

    # Default to confirmed bookings for manifests
    query = query.filter(Booking.status == BookingStatus.CONFIRMED)

    total_bookings = query.count()
    total_passengers = db.query(func.coalesce(func.sum(Booking.passenger_count), 0)).filter(
        Booking.id.in_(query.with_entities(Booking.id))
    ).scalar() or 0

    route_label = f"{from_station} to {to_station}" if (from_station and to_station) else (from_station or to_station or "")

    # If 0 bookings on a requested route, look up available scheduled trains
    operating_services = []
    if total_bookings == 0 and (from_station or to_station or train):
        try:
            from booking.availability import find_matching_services
            services = find_matching_services(origin=from_station, destination=to_station, train_id=train.train_id if train else None)
            for svc, orig_stop, dest_stop in services[:4]:
                operating_services.append({
                    "train_id": svc.train_id,
                    "train_name": svc.train_name,
                    "departure_time": orig_stop.departure_time.strftime("%H:%M") if orig_stop.departure_time else "",
                    "arrival_time": dest_stop.arrival_time.strftime("%H:%M") if dest_stop.arrival_time else "",
                })
        except Exception:
            pass

    if is_count:
        return {
            "type": "count",
            "train_name": train.train_name if train else "All Trains",
            "travel_date": parsed_date.isoformat(),
            "route": route_label,
            "seat_class": target_class,
            "total_bookings": total_bookings,
            "total_passengers": int(total_passengers),
            "operating_services": operating_services,
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
            "contact_email": b.passenger_email,
            "passengers": passengers_info,
            "fare": f"{b.fare:.2f}",
            "status": b.status.value if hasattr(b.status, "value") else str(b.status),
        })

    return {
        "type": "manifest",
        "train_name": train.train_name if train else "All Trains",
        "travel_date": parsed_date.isoformat(),
        "route": route_label,
        "total_bookings": total_bookings,
        "total_passengers": int(total_passengers),
        "bookings": results,
        "operating_services": operating_services,
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
        "passenger_email": booking.passenger_email,
        "passenger_phone": getattr(booking, "passenger_phone", None),
        "user_id": booking.user_id,
        "train_id": booking.train.train_id if booking.train else "",
        "train_name": booking.train.train_name if booking.train else "",
        "route": f"{booking.from_station} to {booking.to_station}",
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


def retrieve_ticket_lookup(db: Session, ticket_ref: str) -> dict[str, Any]:
    """Resolve an opaque ticket token to its linked booking without exposing secrets."""
    clean_ref = ticket_ref.strip().upper()
    booking = db.query(Booking).filter(Booking.ticket_token == clean_ref).first()
    if not booking:
        return {"found": False, "ticket_reference": clean_ref}
    return retrieve_booking_lookup(db, booking.booking_reference)


def retrieve_booking_summary(db: Session, entities: dict[str, Any]) -> dict[str, Any]:
    """
    Compile high-level administrative KPI summary for the current day.
    """
    today = get_current_colombo_date()
    now_utc = datetime.now(timezone.utc)

    # 1. Confirmed bookings created today
    created_today_bookings = db.query(Booking).filter(
        Booking.status == BookingStatus.CONFIRMED,
        func.date(Booking.created_at) == today,
    ).count()

    created_today_pax = db.query(func.coalesce(func.sum(Booking.passenger_count), 0)).filter(
        Booking.status == BookingStatus.CONFIRMED,
        func.date(Booking.created_at) == today,
    ).scalar() or 0

    # 2. Confirmed bookings travelling today
    travel_today_bookings = db.query(Booking).filter(
        Booking.status == BookingStatus.CONFIRMED,
        Booking.travel_date == today,
    ).count()

    travel_today_pax = db.query(func.coalesce(func.sum(Booking.passenger_count), 0)).filter(
        Booking.status == BookingStatus.CONFIRMED,
        Booking.travel_date == today,
    ).scalar() or 0

    # 3. Total active bookings in system
    total_active_bookings = db.query(Booking).filter(
        Booking.status == BookingStatus.CONFIRMED
    ).count()

    # 4. Pending cancellations
    pending_cancellations = db.query(CancellationRequest).filter(
        CancellationRequest.status == CancellationStatus.PENDING_ADMIN_REVIEW
    ).count()

    # 5. Pending fraud reviews
    pending_fraud = db.query(FraudReview).filter(
        FraudReview.status == FraudReviewStatus.PENDING_REVIEW
    ).count()

    # 6. Active seat holds
    active_holds = db.query(SeatHold).filter(
        SeatHold.status == HoldStatus.ACTIVE,
        SeatHold.expires_at > now_utc,
    ).count()

    # 7. Waiting list passengers
    waiting_count = db.query(func.coalesce(func.sum(Booking.passenger_count), 0)).filter(
        Booking.status == BookingStatus.HELD
    ).scalar() or 0

    return {
        "date": today.isoformat(),
        "confirmed_bookings": int(created_today_bookings),
        "passengers": int(created_today_pax),
        "created_today_bookings": int(created_today_bookings),
        "travel_today_bookings": int(travel_today_bookings),
        "travel_today_pax": int(travel_today_pax),
        "total_active_bookings": int(total_active_bookings),
        "pending_cancellations": int(pending_cancellations),
        "pending_fraud_reviews": int(pending_fraud),
        "active_seat_holds": int(active_holds),
        "waiting_list_passengers": int(waiting_count),
        "is_count_request": entities.get("is_count_request", False),
    }
