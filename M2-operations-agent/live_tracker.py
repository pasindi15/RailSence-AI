"""Live journey tracking for the passenger popup.

The board only knows a service's first departure and last arrival. This module
turns that into a station-by-station timetable and works out where the train
is right now, entirely on the server's Asia/Colombo clock:

1. Path       - the calling stations (board stops, or the corridor's standard
                stations when the board has none), each with approximate
                coordinates.
2. Timetable  - every intermediate station gets a scheduled time by sharing the
                end-to-end running time out in proportion to track distance.
3. Disruption - verified incidents from the live map that lie on (or right
                beside) this train's path delay every station after the point
                where they sit. How long each one holds a train is estimated by
                the caller (M2 retrieves similar past incidents for that).
4. Position   - comparing the delayed timetable against "now" gives the status
                (not yet departed / between A and B / at A / arrived), progress
                and the expected time at each station.

Overnight services are handled explicitly: a train leaving 19:15 and arriving
04:30 is "not yet departed" at 18:52, not "arrived" (that was last night's run).
Nothing is random; every minute shown traces back to the schedule, the delay
model or a verified incident.
"""

from __future__ import annotations

import math
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Optional

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Asia/Colombo")
except Exception:  # no tz database on this machine
    LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))

# Approximate WGS84 positions for stations that appear in board stops or on the
# standard corridors but are not in data/station_locations.json (which only
# holds the operations-corpus stations used by the incident map).
EXTRA_STATION_COORDS: dict[str, tuple[float, float]] = {
    "Ragama": (7.0303, 79.9220),
    "Gampaha": (7.0917, 79.9942),
    "Veyangoda": (7.1553, 80.0967),
    "Rambukkana": (7.3236, 80.3936),
    "Kadugannawa": (7.2544, 80.5222),
    "Gampola": (7.1647, 80.5767),
    "Nawalapitiya": (7.0556, 80.5347),
    "Hatton": (6.8917, 80.5953),
    "Talawakele": (6.9372, 80.6589),
    "Pattipola": (6.8561, 80.8317),
    "Bandarawela": (6.8328, 80.9869),
    "Kurunegala": (7.4867, 80.3647),
    "Maho": (7.8228, 80.2778),
    "Galgamuwa": (7.9950, 80.2670),
    "Medawachchiya": (8.5386, 80.4944),
    "Kilinochchi": (9.3961, 80.3981),
    "Mount Lavinia": (6.8390, 79.8650),
    "Moratuwa": (6.7730, 79.8816),
    "Aluthgama": (6.4340, 79.9990),
    "Ambalangoda": (6.2350, 80.0540),
    "Hikkaduwa": (6.1395, 80.1063),
    "Weligama": (5.9750, 80.4290),
    "Habarana": (8.0400, 80.7490),
    "Gal Oya": (8.0700, 80.9370),
    "Kantale": (8.3530, 81.0080),
    "Valaichchenai": (7.9240, 81.5310),
}

# Board names that refer to a corpus station.
STATION_ALIASES = {"colombo": "Colombo Fort", "fort": "Colombo Fort", "colombo fort": "Colombo Fort"}

# Standard calling pattern of each corridor, used when a board row carries no
# stops and to decide whether an incident station lies on this train's line.
CORRIDOR_STATIONS: dict[str, list[str]] = {
    "Kandy": ["Colombo Fort", "Ragama", "Gampaha", "Veyangoda", "Polgahawela", "Rambukkana",
              "Kadugannawa", "Peradeniya", "Kandy"],
    "Badulla": ["Colombo Fort", "Ragama", "Gampaha", "Veyangoda", "Polgahawela", "Rambukkana",
                "Kadugannawa", "Peradeniya", "Gampola", "Nawalapitiya", "Hatton", "Talawakele",
                "Nanu Oya", "Pattipola", "Bandarawela", "Ella", "Badulla"],
    "Jaffna": ["Colombo Fort", "Ragama", "Gampaha", "Veyangoda", "Polgahawela", "Kurunegala", "Maho",
               "Anuradhapura", "Medawachchiya", "Vavuniya", "Kilinochchi", "Jaffna"],
    "Matara": ["Colombo Fort", "Mount Lavinia", "Moratuwa", "Panadura", "Kalutara", "Aluthgama",
               "Ambalangoda", "Hikkaduwa", "Galle", "Weligama", "Matara"],
    "Batticaloa": ["Colombo Fort", "Ragama", "Gampaha", "Veyangoda", "Polgahawela", "Kurunegala", "Maho",
                   "Galgamuwa", "Habarana", "Polonnaruwa", "Valaichchenai", "Batticaloa"],
    "Trincomalee": ["Colombo Fort", "Ragama", "Gampaha", "Veyangoda", "Polgahawela", "Kurunegala", "Maho",
                    "Galgamuwa", "Habarana", "Gal Oya", "Kantale", "Trincomalee"],
}
CORRIDOR_STATIONS["Galle"] = CORRIDOR_STATIONS["Matara"][: CORRIDOR_STATIONS["Matara"].index("Galle") + 1]

# An incident at a station that is not a calling point still affects the train
# when it sits this close to the line between two consecutive calling points.
NEAR_LINE_KM = 4.0
# The train is shown "at" a station for this long either side of its time there.
AT_STATION_MINUTES = 1.0
# A verified incident is treated as already in effect this long before it was
# verified (it was happening before an officer approved it).
INCIDENT_LEAD_MINUTES = 30


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def parse_clock(value: Any) -> Optional[dtime]:
    if not value:
        return None
    try:
        parts = [int(p) for p in str(value).strip().split(":")[:3]]
        while len(parts) < 3:
            parts.append(0)
        return dtime(parts[0], parts[1], parts[2])
    except (ValueError, IndexError):
        return None


class StationIndex:
    """Station name normalisation and coordinates."""

    def __init__(self, corpus_coords: dict[str, tuple[float, float]]):
        self.coords: dict[str, tuple[float, float]] = {**EXTRA_STATION_COORDS, **corpus_coords}
        self._by_fold = {name.casefold(): name for name in self.coords}
        for name in (s for stations in CORRIDOR_STATIONS.values() for s in stations):
            self._by_fold.setdefault(name.casefold(), name)

    def canonical(self, name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        key = " ".join(str(name).split()).casefold()
        return STATION_ALIASES.get(key) or self._by_fold.get(key) or " ".join(str(name).split())

    def names(self) -> list[str]:
        return sorted(set(self._by_fold.values()))


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def _project(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """(fraction along a->b, distance in km from p to that point), flat-earth approx."""
    k = math.cos(math.radians((a[0] + b[0]) / 2))
    ax, ay, bx, by, px, py = a[1] * k, a[0], b[1] * k, b[0], p[1] * k, p[0]
    dx, dy = bx - ax, by - ay
    seg = dx * dx + dy * dy
    t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
    closest = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return t, _km(p, closest)


def corridor_for(stations: StationIndex, origin: Optional[str], destination: Optional[str],
                 route: Optional[str] = None) -> Optional[list[str]]:
    """Standard stations between origin and destination on the matching corridor."""
    o, d = stations.canonical(origin), stations.canonical(destination)
    route_end = stations.canonical(route.split(" - ")[-1]) if route and " - " in route else None
    for end in (d, route_end, o):
        line = CORRIDOR_STATIONS.get(end or "")
        if not line:
            continue
        if o in line and d in line:
            i, j = line.index(o), line.index(d)
            return line[i: j + 1] if i <= j else list(reversed(line[j: i + 1]))
    return None


def build_path(ctx: dict[str, Any], stations: StationIndex) -> list[str]:
    """Ordered calling stations from origin to destination (deduplicated)."""
    origin = stations.canonical(ctx.get("from_station"))
    dest = stations.canonical(ctx.get("to_station"))
    stops = [stations.canonical(s) for s in (ctx.get("stops") or []) if s]
    if not stops:
        stops = corridor_for(stations, origin, dest, ctx.get("route")) or []
    path: list[str] = []
    for name in [origin, *stops, dest]:
        if name and (not path or path[-1] != name) and name not in path:
            path.append(name)
    return path


def _cumulative_km(path: list[str], stations: StationIndex) -> list[float]:
    """Distance of each station from the origin; unknown positions are interpolated evenly."""
    pts = [stations.coords.get(s) for s in path]
    known = [i for i, p in enumerate(pts) if p]
    if len(known) < 2:
        return [float(i) for i in range(len(path))]  # equal spacing
    dist = [0.0] * len(path)
    for a, b in zip(known, known[1:]):
        leg = _km(pts[a], pts[b])
        for k in range(a + 1, b + 1):
            dist[k] = dist[a] + leg * (k - a) / (b - a)
    # stations before the first / after the last known coordinate: extend evenly
    step = (dist[known[-1]] - dist[known[0]]) / max(1, known[-1] - known[0])
    for k in range(known[0] - 1, -1, -1):
        dist[k] = dist[k + 1] - step
    for k in range(known[-1] + 1, len(path)):
        dist[k] = dist[k - 1] + step
    base = dist[0]
    return [d - base for d in dist]


def locate_incident(incident: dict[str, Any], path: list[str], cum_km: list[float],
                    stations: StationIndex, corridor: Optional[list[str]]) -> Optional[dict[str, Any]]:
    """Where along the path an incident sits, or None when it's off this train's line."""
    station = stations.canonical(incident.get("station"))
    total = cum_km[-1] or 1.0
    if station in path:
        i = path.index(station)
        return {"fraction": cum_km[i] / total, "after": path[i], "before": path[i], "on": "station"}
    point = stations.coords.get(station) if station else None
    if point is None and incident.get("lat") is not None and incident.get("lon") is not None:
        point = (float(incident["lat"]), float(incident["lon"]))
    if point is None:
        return None
    on_corridor = bool(corridor and station in corridor)
    best = None
    for i in range(len(path) - 1):
        a, b = stations.coords.get(path[i]), stations.coords.get(path[i + 1])
        if not a or not b:
            continue
        t, off = _project(point, a, b)
        if best is None or off < best[1]:
            best = (i, off, t)
    if best is None:
        return None
    i, off, t = best
    # A corridor station the board simply doesn't list as a stop is on the line
    # by definition; anything else must sit right beside the track.
    if not on_corridor and off > NEAR_LINE_KM:
        return None
    frac = (cum_km[i] + (cum_km[i + 1] - cum_km[i]) * t) / total
    return {"fraction": frac, "after": path[i], "before": path[i + 1], "on": "between"}


def _fmt(dt: Optional[datetime], ref: Optional[datetime] = None) -> Optional[str]:
    if dt is None:
        return None
    text = dt.strftime("%H:%M")
    if ref is not None:
        days = (dt.date() - ref.date()).days
        if days > 0:
            text += " (+1)" if days == 1 else f" (+{days})"
    return text


def _run_timeline(run_start: datetime, duration: timedelta, path: list[str], cum_km: list[float],
                  disruptions: list[dict[str, Any]], baseline_minutes: float) -> list[dict[str, Any]]:
    total = cum_km[-1] or 1.0
    rows = []
    for name, km in zip(path, cum_km):
        frac = km / total
        scheduled = run_start + duration * frac
        reasons, extra = [], 0.0
        for d in disruptions:
            # Delay is felt from the incident point onwards; a station exactly at
            # the incident is already held there.
            if frac + 1e-9 >= d["fraction"] and d["applies_to_run"](run_start + duration * d["fraction"]):
                extra += d["delay_minutes"]
                reasons.append(d["id"])
        delay = baseline_minutes * frac + extra
        rows.append({"station": name, "fraction": frac, "scheduled_dt": scheduled,
                     "expected_dt": scheduled + timedelta(minutes=delay),
                     "delay_minutes": round(delay, 1), "incident_minutes": round(extra, 1),
                     "reasons": reasons})
    return rows


def compute_live(
    ctx: dict[str, Any],
    stations: StationIndex,
    incidents: list[dict[str, Any]],
    impact_for: Callable[[dict[str, Any], str], dict[str, Any]],
    baseline_minutes: float = 0.0,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Station-by-station timetable and live position for one service.

    incidents:   verified map-feed items (station, incident_type, summary, verified_at, id)
    impact_for:  (incident, corridor_label) -> {"minutes", "basis", "samples"}
    baseline_minutes: typical running delay from the delay model, spread along the run
    """
    dep, arr = parse_clock(ctx.get("departure_time")), parse_clock(ctx.get("arrival_time"))
    path = build_path(ctx, stations)
    if dep is None or arr is None or len(path) < 2:
        return None
    now = (now or local_now()).astimezone(LOCAL_TZ)
    cum_km = _cumulative_km(path, stations)
    corridor = corridor_for(stations, path[0], path[-1], ctx.get("route"))
    duration = (datetime.combine(now.date(), arr) - datetime.combine(now.date(), dep))
    if duration <= timedelta(0):
        duration += timedelta(days=1)  # overnight service
    baseline = max(0.0, float(baseline_minutes or 0))

    # Locate every on-route incident once; whether it applies depends on the run.
    disruptions = []
    route_label = f"{path[0]} - {path[-1]}"
    for inc in incidents:
        where = locate_incident(inc, path, cum_km, stations, corridor)
        if not where:
            continue
        impact = impact_for(inc, route_label) or {}
        minutes = float(impact.get("minutes") or 0)
        if minutes <= 0:
            continue
        try:
            verified = datetime.fromisoformat(str(inc.get("verified_at")).replace("Z", "+00:00"))
            if verified.tzinfo is None:
                verified = verified.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            verified = None
        # The incident only holds this run if the train reaches its location
        # after it started (verified minus a short lead time).
        effective_from = verified - timedelta(minutes=INCIDENT_LEAD_MINUTES) if verified else None
        disruptions.append({
            "id": str(inc.get("id") or inc.get("incident_id") or len(disruptions)),
            "station": stations.canonical(inc.get("station")),
            "incident_type": inc.get("incident_type") or inc.get("classified_type") or "other",
            "summary": inc.get("summary") or "",
            "delay_minutes": round(minutes, 1),
            "basis": impact.get("basis") or "",
            "samples": impact.get("samples") or 0,
            "fraction": where["fraction"],
            "after": where["after"], "before": where["before"], "on": where["on"],
            "applies_to_run": (lambda passage, ef=effective_from: ef is None or passage >= ef),
        })
    disruptions.sort(key=lambda d: d["fraction"])

    # Pick the run that matters now: last night's overnight run while it's
    # still on the rails, otherwise today's run.
    def run_for(start_day_offset: int) -> tuple[datetime, list[dict[str, Any]]]:
        start = datetime.combine(now.date() + timedelta(days=start_day_offset), dep, tzinfo=LOCAL_TZ)
        return start, _run_timeline(start, duration, path, cum_km, disruptions, baseline)

    start, rows = run_for(0)
    prev_start, prev_rows = run_for(-1)
    if now < start and now < prev_rows[-1]["expected_dt"]:
        start, rows = prev_start, prev_rows

    first, last = rows[0], rows[-1]
    if now < first["expected_dt"]:
        status = "SCHEDULED"
    elif now >= last["expected_dt"]:
        status = "ARRIVED"
    else:
        status = "IN_TRANSIT"

    current = next_row = None
    progress = 0.0
    at_station = None
    if status == "ARRIVED":
        current, progress = last, 100.0
    elif status == "IN_TRANSIT":
        passed = [r for r in rows if r["expected_dt"] <= now]
        upcoming = [r for r in rows if r["expected_dt"] > now]
        current, next_row = passed[-1], upcoming[0]
        span = (next_row["expected_dt"] - current["expected_dt"]).total_seconds() or 1.0
        t = (now - current["expected_dt"]).total_seconds() / span
        progress = 100.0 * (current["fraction"] + (next_row["fraction"] - current["fraction"]) * t)
        for r in (current, next_row):
            if abs((now - r["expected_dt"]).total_seconds()) <= AT_STATION_MINUTES * 60:
                at_station = r
                break
    else:
        next_row = first

    minutes_to_next = None
    if next_row is not None:
        minutes_to_next = max(0, round((next_row["expected_dt"] - now).total_seconds() / 60))

    applied_ids = {rid for r in rows for rid in r["reasons"]}
    public_disruptions = [
        {k: v for k, v in d.items() if k != "applies_to_run"} | {"affects_this_run": d["id"] in applied_ids}
        for d in disruptions
    ]
    for d in public_disruptions:
        d["fraction"] = round(d["fraction"], 3)

    timeline = []
    for r in rows:
        state = "passed" if r["expected_dt"] <= now else "upcoming"
        if at_station is r:
            state = "current"
        timeline.append({
            "station": r["station"],
            "scheduled": _fmt(r["scheduled_dt"], start),
            "expected": _fmt(r["expected_dt"], start),
            "delay_minutes": round(r["delay_minutes"]),
            "incident_minutes": round(r["incident_minutes"]),
            "state": state,
            "reasons": r["reasons"],
        })

    return {
        "now": now.strftime("%H:%M"),
        "status": "AT_STATION" if at_station is not None and status == "IN_TRANSIT" else status,
        "service_day": "yesterday" if start.date() < now.date() else "today",
        "departs_at": _fmt(first["expected_dt"]),
        "scheduled_departure": _fmt(first["scheduled_dt"]),
        "scheduled_arrival": _fmt(last["scheduled_dt"], start),
        "expected_arrival": _fmt(last["expected_dt"], start),
        "delay_minutes": round(last["delay_minutes"]),
        "incident_minutes": round(last["incident_minutes"]),
        "baseline_minutes": round(baseline),
        "current_station": (at_station or current or {}).get("station") if status != "SCHEDULED" else path[0],
        "last_station": current["station"] if current else None,
        "next_station": next_row["station"] if next_row and status != "ARRIVED" else None,
        "at_station": at_station["station"] if at_station is not None else None,
        "minutes_to_next": minutes_to_next,
        "progress_percent": round(max(0.0, min(100.0, progress))),
        "path_source": "board_stops" if ctx.get("stops") else ("corridor" if corridor else "endpoints"),
        "run_start": start.isoformat(),
        "duration_minutes": round(duration.total_seconds() / 60, 1),
        "timeline": timeline,
        "disruptions": public_disruptions,
    }


def station_fraction(ctx: dict[str, Any], station: str, stations: StationIndex) -> Optional[float]:
    """How far along this service's journey a station sits (0..1), or None if off its line.

    Works for calling stations and for corridor stations the board doesn't list
    (e.g. Polonnaruwa on a Colombo Fort -> Batticaloa train that lists Habarana
    and Batticaloa only).
    """
    path = build_path(ctx, stations)
    if len(path) < 2:
        return None
    cum_km = _cumulative_km(path, stations)
    corridor = corridor_for(stations, path[0], path[-1], ctx.get("route"))
    where = locate_incident({"station": station}, path, cum_km, stations, corridor)
    return where["fraction"] if where else None


def passage_at(live: dict[str, Any], fraction: float) -> dict[str, Any]:
    """Scheduled and expected time at a point along the run described by `live`."""
    start = datetime.fromisoformat(live["run_start"])
    scheduled = start + timedelta(minutes=live["duration_minutes"] * fraction)
    delay = live["baseline_minutes"] * fraction + sum(
        d["delay_minutes"] for d in live["disruptions"]
        if d.get("affects_this_run") and d["fraction"] <= fraction + 1e-9)
    expected = scheduled + timedelta(minutes=delay)
    return {"scheduled_dt": scheduled, "expected_dt": expected,
            "scheduled": _fmt(scheduled, start), "expected": _fmt(expected, start),
            "delay_minutes": round(delay)}


def find_station_mention(question: str, candidates: list[str], stations: StationIndex) -> Optional[str]:
    """Named-entity step: which of this train's stations the passenger mentioned.

    Exact (word-boundary) matches first, then a fuzzy match on word n-grams so
    small typos ("kandi", "polgahawla") still resolve.
    """
    import difflib
    import re

    text = " " + re.sub(r"[^\w\s]", " ", question.casefold()) + " "
    names = {c.casefold(): c for c in candidates}
    for alias, target in STATION_ALIASES.items():
        if target in candidates:
            names.setdefault(alias, target)
    for key in sorted(names, key=len, reverse=True):
        if f" {key} " in text:
            return names[key]
    words = text.split()
    grams = {" ".join(words[i:i + n]) for n in (1, 2) for i in range(len(words) - n + 1)}
    grams = {g for g in grams if len(g) >= 4}
    best, best_score = None, 0.0
    for g in grams:
        for key, name in names.items():
            score = difflib.SequenceMatcher(None, g, key).ratio()
            if score > best_score:
                best, best_score = name, score
    return best if best_score >= 0.82 else None
