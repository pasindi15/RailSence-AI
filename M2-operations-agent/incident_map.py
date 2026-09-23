"""Verified-incident map feed shared by the Control Room, Admin Console and
the passenger portal.

Only incidents an administrator has approved (review_status == "verified")
ever leave this module, and only through public_item(), which copies an
explicit allowlist of fields - raw_text, nlp_method, reviewed_by and every
other internal column are never serialised. The passenger page is
unauthenticated, so this allowlist is the privacy boundary.

Coordinates come from data/station_locations.json, keyed by the station names
of the operations corpus (data/operations_history.csv). An approved incident
at a station with no known location is counted as `unmapped` rather than
being placed at a guessed position.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("railsense.incident_map")

VERIFIED = "verified"

# The map is a "today" view: only incidents verified since local midnight are
# shown, so at 00:00 Sri Lanka time the previous day's markers drop off.
try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Asia/Colombo")
except Exception:  # no tz database on this machine
    LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))
LOCATIONS_PATH = Path(__file__).parent / "data" / "station_locations.json"
SUMMARY_LIMIT = 180
CACHE_TTL_SECONDS = 2.0


def _load_locations() -> dict[str, tuple[float, float]]:
    try:
        raw = json.loads(LOCATIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("station_locations.json unavailable: %s", exc)
        return {}
    return {name: (float(v[0]), float(v[1])) for name, v in raw.items() if not name.startswith("_")}


STATION_LOCATIONS = _load_locations()
_BY_CASEFOLD = {name.casefold(): name for name in STATION_LOCATIONS}


def canonical_station(station: Optional[str]) -> Optional[str]:
    """Return the corpus spelling of a station, or None if it has no location."""
    if not station:
        return None
    return _BY_CASEFOLD.get(str(station).strip().casefold())


def station_list() -> list[dict[str, Any]]:
    return [{"station": name, "lat": lat, "lon": lon}
            for name, (lat, lon) in sorted(STATION_LOCATIONS.items())]


def verified_at_of(row: dict[str, Any]) -> Optional[str]:
    """verified_at column when present, else the approval's reviewed_at stamp."""
    if row.get("verified_at"):
        return str(row["verified_at"])
    reviewed = row.get("reviewed_at")
    if isinstance(reviewed, (int, float)):
        return datetime.fromtimestamp(reviewed, tz=timezone.utc).isoformat()
    return str(reviewed) if reviewed else None


def public_item(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Allowlisted map marker for one row; None if it must not be shown."""
    if str(row.get("review_status", "")).lower() != VERIFIED:
        return None
    station = canonical_station(row.get("station"))
    if station is None:
        return None
    lat, lon = STATION_LOCATIONS[station]
    summary = " ".join(str(row.get("summary") or "").split())
    if len(summary) > SUMMARY_LIMIT:
        summary = summary[: SUMMARY_LIMIT - 1].rstrip() + "…"
    return {
        "id": str(row.get("incident_id")),
        "train_id": row.get("train_id"),
        "station": station,
        "lat": lat,
        "lon": lon,
        "incident_type": row.get("classified_type") or "other",
        "summary": summary,
        "verified_at": verified_at_of(row),
        "status": "VERIFIED",
    }


def local_midnight(now: Optional[datetime] = None) -> datetime:
    """00:00 today in Sri Lanka time, as an aware datetime."""
    now = (now or datetime.now(timezone.utc)).astimezone(LOCAL_TZ)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def verified_today(item: dict[str, Any], midnight: datetime) -> bool:
    try:
        stamp = datetime.fromisoformat(str(item.get("verified_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False  # no verification time: can't tell which day it belongs to
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp >= midnight


class MapFeed:
    """Builds the feed, with a short TTL cache and a last-known fallback.

    Three pages poll every few seconds; the TTL collapses those polls into
    one store read. If the store read fails outright, the last good feed is
    served with stale=true instead of an error, so no map ever crashes the
    service or goes blank on a transient outage.
    """

    def __init__(self, fetch_rows: Callable[[], dict[str, Any]],
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._fetch_rows = fetch_rows
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: Optional[dict[str, Any]] = None
        self._cached_at = 0.0

    def invalidate(self) -> None:
        with self._lock:
            self._cached_at = 0.0

    def get(self) -> dict[str, Any]:
        """Today's verified incidents; the cutoff is recomputed on every call."""
        with self._lock:
            midnight = local_midnight(self._clock())
            if (self._cached and self._cached.get("since") == midnight.isoformat()
                    and time.monotonic() - self._cached_at < CACHE_TTL_SECONDS):
                return self._cached
            try:
                result = self._fetch_rows()
                rows = result.get("rows", [])
                items = [item for item in (public_item(r) for r in rows)
                         if item and verified_today(item, midnight)]
                items.sort(key=lambda i: i.get("verified_at") or "", reverse=True)
                verified = sum(1 for r in rows
                               if str(r.get("review_status", "")).lower() == VERIFIED
                               and verified_today({"verified_at": verified_at_of(r)}, midnight))
                feed = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "source": result.get("source", "unknown"),
                    "offline": result.get("source") != "supabase",
                    "stale": False,
                    "day": midnight.date().isoformat(),
                    "since": midnight.isoformat(),
                    "incidents": items,
                    "unmapped": verified - len(items),
                }
            except Exception as exc:
                logger.warning("map feed read failed, serving last known: %s", exc)
                feed = dict(self._cached or {"incidents": [], "unmapped": 0, "source": "unavailable"})
                # Even the last-known copy must not carry yesterday's markers past midnight.
                feed["incidents"] = [i for i in feed.get("incidents", []) if verified_today(i, midnight)]
                feed.update({"generated_at": datetime.now(timezone.utc).isoformat(),
                             "day": midnight.date().isoformat(), "since": midnight.isoformat(),
                             "offline": True, "stale": True})
            self._cached, self._cached_at = feed, time.monotonic()
            return feed
