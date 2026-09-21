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

# Local fallback used when the Supabase trains table is empty or unreachable.
# Keeps T-001..T-008 resolvable in dev environments without a seeded DB.
_LOCAL_TRAINS: dict[str, dict[str, Any]] = {
    "T-001": {"train_id": "T-001", "train_name": "Udarata Menike",   "active": True, "route": "Colombo Fort - Badulla",  "origin_station": "Colombo Fort", "destination_station": "Badulla",  "maintenance_status": None},
    "T-002": {"train_id": "T-002", "train_name": "Intercity Express","active": True, "route": "Colombo Fort - Kandy",    "origin_station": "Colombo Fort", "destination_station": "Kandy",    "maintenance_status": None},
    "T-003": {"train_id": "T-003", "train_name": "Yal Devi",         "active": True, "route": "Colombo Fort - Jaffna",   "origin_station": "Colombo Fort", "destination_station": "Jaffna",   "maintenance_status": None},
    "T-004": {"train_id": "T-004", "train_name": "Ruhunu Kumari",    "active": True, "route": "Colombo Fort - Matara",   "origin_station": "Colombo Fort", "destination_station": "Matara",   "maintenance_status": None},
    "T-005": {"train_id": "T-005", "train_name": "Podi Menike",      "active": True, "route": "Kandy - Badulla",         "origin_station": "Kandy",        "destination_station": "Badulla",  "maintenance_status": None},
    "T-006": {"train_id": "T-006", "train_name": "Galu Kumari",      "active": True, "route": "Colombo Fort - Galle",    "origin_station": "Colombo Fort", "destination_station": "Galle",    "maintenance_status": None},
    "T-007": {"train_id": "T-007", "train_name": "Night Mail",       "active": True, "route": "Colombo Fort - Matara",   "origin_station": "Colombo Fort", "destination_station": "Matara",   "maintenance_status": None},
    "T-008": {"train_id": "T-008", "train_name": "Denuwara Menike",  "active": True, "route": "Colombo Fort - Kandy",    "origin_station": "Colombo Fort", "destination_station": "Kandy",    "maintenance_status": None},
}


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


def _exact_train(clean_id: str) -> dict[str, Any] | None:
    """Look a canonical train_id up verbatim, with no alias resolution."""
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
    return response.data[0] if response.data else None


def _alias_candidates(clean_id: str) -> list[dict[str, Any]]:
    """Active canonical rows a passenger's shorthand could be referring to.

    The registry deliberately carries two naming conventions side by side (see
    SHARED_TRAIN_SOURCE_OF_TRUTH.md): prefixed operational ids like PM-4082,
    and bare Sri Lanka Railways service numbers like 50 or 1015. Passengers
    type whichever they have seen, so "4082" has to be able to reach PM-4082 -
    but only when the registry leaves no genuine doubt about which train that
    is. Roughly one numeric suffix in eight is shared by two or more trains
    (IC-1048 and UD-1048, for example), and answering for the wrong one is
    worse than saying we are not sure, so the caller is handed every candidate
    rather than an arbitrary pick.
    """
    try:
        if clean_id.isdigit():
            # Bare service number -> any prefixed id ending in "-<number>".
            # The '-' anchors it so "82" can never reach "PM-4082".
            response = (
                get_client()
                .table("trains")
                .select("*")
                .ilike("train_id", f"%-{clean_id}")
                .eq("active", True)
                .execute()
            )
        elif "-" in clean_id and clean_id.rsplit("-", 1)[1].isdigit():
            # Prefixed id that is not in the registry under that prefix ->
            # try the bare service number it is built from.
            response = (
                get_client()
                .table("trains")
                .select("*")
                .eq("train_id", clean_id.rsplit("-", 1)[1])
                .eq("active", True)
                .execute()
            )
        else:
            return []
    except Exception as exc:
        raise TrainRepositoryUnavailable("Canonical train lookup failed") from exc
    return response.data or []


def resolve_train(train_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Resolve caller-supplied text to one canonical train row.

    Returns (row, candidates). An exact registry hit always wins and returns
    ([] , no candidates). Otherwise an unambiguous alias resolves to its single
    canonical row. When the shorthand is ambiguous, row is None and every
    candidate is returned so the caller can ask which train was meant instead
    of guessing on the passenger's behalf.
    Falls back to _LOCAL_TRAINS when Supabase has no matching row.
    """
    clean_id = (train_id or "").strip().upper()
    if not clean_id:
        return None, []

    try:
        exact = _exact_train(clean_id)
        if exact is not None:
            return exact, []

        candidates = _alias_candidates(clean_id)
        if len(candidates) == 1:
            return candidates[0], []
        if candidates:
            return None, candidates
    except TrainRepositoryUnavailable:
        pass

    # Supabase unavailable or returned nothing — use the local fallback map.
    local = _LOCAL_TRAINS.get(clean_id)
    if local:
        return local, []
    return None, []


def get_train(train_id: str) -> dict[str, Any] | None:
    """Return the canonical train row for a public train_id.

    Exact matches win. An unambiguous alias (a bare service number for a
    prefixed id, or vice versa) resolves to its canonical row; an ambiguous
    one returns None rather than guessing. Use resolve_train() when the caller
    can act on the ambiguous candidates.
    """
    row, _candidates = resolve_train(train_id)
    return row


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
        if response.data:
            return response.data
    except Exception:
        pass

    # Supabase unavailable or empty — filter local fallback.
    results = list(_LOCAL_TRAINS.values())
    if origin:
        results = [t for t in results if origin.lower() in (t.get("origin_station") or "").lower()]
    if destination:
        results = [t for t in results if destination.lower() in (t.get("destination_station") or "").lower()]
    return results


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
    return response.data or []


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
        "updated_at": train.get("updated_at"),
    }

    maintenance_status = str(train.get("maintenance_status") or "").upper()
    if not train.get("active") or maintenance_status in {"OUT_OF_SERVICE", "DECOMMISSIONED"}:
        details["status"] = "OUT_OF_SERVICE"

    metadata = train.get("metadata") or {}
    if isinstance(metadata, dict):
        delay = metadata.get("delay_minutes", metadata.get("current_delay_minutes"))
        if isinstance(delay, (int, float)):
            details["delay_minutes"] = delay
            if delay > 0 and details["status"] == "ON_TIME":
                details["status"] = "DELAYED"

    snapshot_availability = train.get("current_class_availability")

    if schedule:
        service_status = str(schedule.get("service_status") or "SCHEDULED").upper()
        if service_status in {"CANCELLED", "OUT_OF_SERVICE"}:
            details["status"] = service_status
        details["schedule"] = {
            "from_station": schedule.get("from_station"),
            "to_station": schedule.get("to_station"),
            "travel_date": schedule.get("travel_date"),
            "departure_time": schedule.get("departure_time"),
            "arrival_time": schedule.get("arrival_time"),
            "platform": schedule.get("platform"),
            "service_status": service_status,
        }
        capacities = {
            "First Class": schedule.get("first_class_capacity"),
            "Second Class": schedule.get("second_class_capacity"),
        }
        try:
            booking_rows = (
                get_client()
                .table("bookings")
                .select("seat_class,passenger_count,status")
                .eq("schedule_id", schedule.get("id"))
                .execute()
                .data
            )
            booked: dict[str, int] = {seat_class: 0 for seat_class in capacities}
            for booking in booking_rows or []:
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
