"""Read-only access to the canonical Supabase train registry.

This module contains no agent business logic. M1 and M2 use it to resolve the
same train identity before applying their existing local workflows.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

ROOT_DIR = Path(__file__).resolve().parents[1]
_client: Client | None = None


class TrainRepositoryUnavailable(RuntimeError):
    """Raised when the canonical train database cannot be reached/configured."""


def _load_root_env() -> None:
    load_dotenv(ROOT_DIR / ".env", override=False)


def get_client() -> Client:
    global _client
    if _client is not None:
        return _client
    _load_root_env()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    if not url or not key:
        raise TrainRepositoryUnavailable("Canonical train database is not configured")
    try:
        _client = create_client(url, key)
    except Exception as exc:
        raise TrainRepositoryUnavailable("Canonical train database client could not be created") from exc
    return _client


def get_train(train_id: str) -> dict[str, Any] | None:
    """Return the canonical train row for an exact public train_id."""
    clean_id = (train_id or "").strip().upper()
    if not clean_id:
        return None
    try:
        response = (
            get_client()
            .table("trains")
            .select("*")
            .eq("train_id", clean_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise TrainRepositoryUnavailable("Canonical train lookup failed") from exc
    rows: list[dict[str, Any]] = response.data or []  # type: ignore[assignment]
    return rows[0] if rows else None


def search_trains(
    origin: str | None = None,
    destination: str | None = None,
) -> list[dict[str, Any]]:
    """Search canonical train identities by optional origin/destination."""
    try:
        query = get_client().table("trains").select("*").eq("active", True)
        if origin:
            query = query.ilike("origin_station", f"%{origin.strip()}%")
        if destination:
            query = query.ilike("destination_station", f"%{destination.strip()}%")
        response = query.order("train_id").execute()
    except Exception as exc:
        raise TrainRepositoryUnavailable("Canonical train search failed") from exc
    data: list[dict[str, Any]] = response.data or []  # type: ignore[assignment]
    return data


def get_train_schedule(train_id: str) -> list[dict[str, Any]]:
    """Return date-specific schedules linked to a canonical train row."""
    train = get_train(train_id)
    if train is None:
        return []
    try:
        response = (
            get_client()
            .table("train_schedules")
            .select("*")
            .eq("train_id", train["id"])
            .order("travel_date")
            .execute()
        )
    except Exception as exc:
        raise TrainRepositoryUnavailable("Canonical train schedule lookup failed") from exc
    data: list[dict[str, Any]] = response.data or []  # type: ignore[assignment]
    return data


def _add_minutes_to_time(time_str: str | None, minutes: float | None) -> str | None:
    if not time_str or not minutes:
        return time_str
    try:
        parts = time_str.split(":")
        h = int(parts[0])
        m = int(parts[1])
        total_mins = int(h * 60 + m + round(minutes))
        new_h = (total_mins // 60) % 24
        new_m = total_mins % 60
        return f"{new_h:02d}:{new_m:02d}"
    except Exception:
        return time_str


def get_services_for_date(
    origin: str | None = None,
    destination: str | None = None,
    travel_date: str | Any | None = None,
) -> list[dict[str, Any]]:
    """Return all canonical scheduled services for a given date and route."""
    from datetime import date
    if not travel_date:
        travel_date = date.today().isoformat()
    elif isinstance(travel_date, date):
        travel_date = travel_date.isoformat()

    client = get_client()
    try:
        query = client.table("train_schedules").select("*, trains(*)").eq("travel_date", travel_date)
        if origin:
            clean_origin = origin.strip()
            if clean_origin.casefold() in ("colombo", "colombo fort"):
                query = query.in_("from_station", ["Colombo Fort", "Colombo"])
            else:
                query = query.ilike("from_station", f"%{clean_origin}%")
        if destination:
            clean_dest = destination.strip()
            query = query.ilike("to_station", f"%{clean_dest}%")

        response = query.order("departure_time").execute()
        rows: list[dict[str, Any]] = response.data or []  # type: ignore[assignment]
    except Exception as exc:
        raise TrainRepositoryUnavailable("Failed to query train services for date") from exc

    import re
    seen_trains = set()
    services = []
    for _r in rows:
        r: dict[str, Any] = dict(_r)  # type: narrow from Supabase JSON
        train: dict[str, Any] = dict(r.get("trains") or {})
        train_id = train.get("train_id") or str(r.get("train_id"))
        if not re.match(r"^[A-Z]{2,12}-\d{3,5}$", train_id, re.IGNORECASE):
            continue

        dep_time = str(r.get("departure_time") or "")
        dedup_key = (train_id, dep_time[:5])
        if dedup_key in seen_trains:
            continue
        seen_trains.add(dedup_key)

        metadata = train.get("metadata") or {}
        stops = metadata.get("stops") or r.get("stops") or []
        stop_times = metadata.get("stop_times") or {}
        delay = metadata.get("delay_minutes", metadata.get("current_delay_minutes", 0))

        status = str(r.get("service_status") or "SCHEDULED").upper()
        if delay and delay > 0 and status in ("SCHEDULED", "ON_TIME"):
            status = "DELAYED"

        # Normalize station name: "Colombo" alias -> "Colombo Fort"
        raw_from = r.get("from_station") or train.get("origin_station") or ""
        raw_to = r.get("to_station") or train.get("destination_station") or ""
        norm_from = "Colombo Fort" if raw_from.strip().casefold() == "colombo" else raw_from
        norm_to = "Colombo Fort" if raw_to.strip().casefold() == "colombo" else raw_to

        services.append({
            "train_id": train_id,
            "train_name": train.get("train_name"),
            "from_station": norm_from,
            "to_station": norm_to,
            "route": train.get("route") or f"{norm_from} - {norm_to}",
            "departure_time": dep_time[:5] if dep_time else "N/A",
            "arrival_time": str(r.get("arrival_time") or "")[:5] or "N/A",
            "service_status": status,
            "maintenance_status": str(train.get("maintenance_status") or "UNKNOWN").upper(),
            "delay_minutes": delay,
            "stops": stops,
            "stop_times": stop_times,
            "platform": r.get("platform", "1"),
            "travel_date": travel_date,
            "first_class_capacity": r.get("first_class_capacity"),
            "second_class_capacity": r.get("second_class_capacity"),
        })

    return services


def get_train_details(train_id: str) -> dict[str, Any] | None:
    """Return a presentation-ready snapshot from the shared train tables."""
    train = get_train(train_id)
    if train is None:
        return None

    schedules = get_train_schedule(train_id)
    schedule = schedules[0] if schedules else None
    details: dict[str, Any] = {
        "train_id": train.get("train_id"),
        "train_name": train.get("train_name"),
        "active": train.get("active"),
        "maintenance_status": train.get("maintenance_status"),
        "route": train.get("route"),
        "origin_station": train.get("origin_station"),
        "destination_station": train.get("destination_station"),
        "status": "ON_TIME",
        "delay_minutes": None,
        "schedule": None,
        "availability": None,
        "stops": [],
        "stop_times": {},
        "scheduled_departure": None,
        "scheduled_arrival": None,
        "expected_departure": None,
        "expected_arrival": None,
        "confidence": "85%",
        "alert_status": "NORMAL",
        "similar_incident": None,
        "updated_at": train.get("updated_at"),
    }

    maintenance_status = str(train.get("maintenance_status") or "").upper()
    if not train.get("active") or maintenance_status in {"OUT_OF_SERVICE", "DECOMMISSIONED"}:
        details["status"] = "OUT_OF_SERVICE"

    metadata = train.get("metadata") or {}
    if isinstance(metadata, dict):
        details["stops"] = metadata.get("stops") or []
        details["stop_times"] = metadata.get("stop_times") or {}
        delay = metadata.get("delay_minutes", metadata.get("current_delay_minutes"))
        if isinstance(delay, (int, float)):
            details["delay_minutes"] = delay
            if delay > 0 and details["status"] == "ON_TIME":
                details["status"] = "DELAYED"
    else:
        details["stops"] = []
        details["stop_times"] = {}

    # Fallback: if metadata has no stops, try to reconstruct from origin/destination
    if not details["stops"] and train.get("origin_station") and train.get("destination_station"):
        details["stops"] = [train["origin_station"], train["destination_station"]]

    if (details.get("delay_minutes") or 0) >= 5.0:
        details["alert_status"] = "ALERT_REQUIRED"

    snapshot_availability = train.get("current_class_availability")

    if schedule:
        service_status = str(schedule.get("service_status") or "SCHEDULED").upper()
        if service_status in {"CANCELLED", "OUT_OF_SERVICE"}:
            details["status"] = service_status
        dep = str(schedule.get("departure_time") or "")
        arr = str(schedule.get("arrival_time") or "")
        dep_short = dep[:5] if dep else None
        arr_short = arr[:5] if arr else None
        delay_val = details.get("delay_minutes") or 0

        details["scheduled_departure"] = dep_short
        details["scheduled_arrival"] = arr_short
        details["expected_departure"] = _add_minutes_to_time(dep_short, delay_val)
        details["expected_arrival"] = _add_minutes_to_time(arr_short, delay_val)

        details["schedule"] = {
            "from_station": schedule.get("from_station"),
            "to_station": schedule.get("to_station"),
            "travel_date": schedule.get("travel_date"),
            "departure_time": dep_short,
            "arrival_time": arr_short,
            "platform": schedule.get("platform", "1"),
            "service_status": service_status,
        }
        capacities = {
            "First Class": schedule.get("first_class_capacity"),
            "Second Class": schedule.get("second_class_capacity"),
        }
        try:
            booking_response = (
                get_client()
                .table("bookings")
                .select("seat_class,passenger_count,status")
                .eq("schedule_id", schedule.get("id"))
                .execute()
            )
            booking_rows: list[dict[str, Any]] = booking_response.data or []  # type: ignore[assignment]
            booked: dict[str, int] = {seat_class: 0 for seat_class in capacities}
            for booking in booking_rows:
                if str(booking.get("status") or "").upper() != "CONFIRMED":
                    continue
                seat_class = str(booking.get("seat_class") or "").strip().title()
                if seat_class in booked:
                    booked[seat_class] += int(booking.get("passenger_count") or 0)
            details["availability"] = {
                seat_class: max(0, int(capacity) - booked[seat_class])
                for seat_class, capacity in capacities.items()
                if capacity is not None
            }
        except Exception:
            details["availability"] = snapshot_availability if isinstance(snapshot_availability, dict) else None

    return details
