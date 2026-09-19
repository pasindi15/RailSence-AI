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
    return response.data[0] if response.data else None


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
    return response.data or []


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
