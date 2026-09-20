"""
booking/services_catalog.py
---------------------------
Canonical catalog of recurring daily train services derived from
M1-passenger_assistant/backend/data/faq_docs/schedules.md and canonical project fixtures.

Operating Assumption Note:
-------------------------
All imported services are configured to run every day (Monday through Sunday,
operating_days = [0, 1, 2, 3, 4, 5, 6]) as an internal project design assumption.
This assumption must not be presented as a verified real-world Sri Lanka Railways timetable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class ServiceStop:
    """A scheduled intermediate or terminal stop for a train service."""
    station: str
    arrival_time: time | None
    departure_time: time | None
    day_offset: int = 0  # 0 for same-day originating run, 1 for overnight arrival day


@dataclass(frozen=True)
class DailyService:
    """A recurring daily train service specification."""
    service_id: str
    train_id: str
    train_name: str
    origin_station: str
    destination_station: str
    route: str
    departure_time: time
    arrival_time: time
    stops: tuple[ServiceStop, ...]
    is_overnight: bool = False
    first_class_capacity: int = 40
    second_class_capacity: int = 120
    operating_days: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)  # 0=Monday, 6=Sunday


# Normalization aliases for Sri Lankan railway stations
STATION_ALIASES: dict[str, list[str]] = {
    "colombo fort": ["colombo", "colombo fort", "fort", "කොළඹ කොටුව", "கொழும்பு கோட்டை"],
    "maradana": ["maradana", "මරදාන", "மருதானை"],
    "kandy": ["kandy", "මහනුවර", "கண்டி"],
    "nanu oya": ["nanu oya", "nanuoya", "නානුඔය", "நானு ஓயா"],
    "ella": ["ella", "ඇල්ල", "எல்ல"],
    "badulla": ["badulla", "බදුල්ල", "பதுளை"],
    "galle": ["galle", "ගාල්ල", "காலி"],
    "matara": ["matara", "මාතර", "மாத்தறை"],
    "kurunegala": ["kurunegala", "කුරුණෑගල", "குருணாகல்"],
    "anuradhapura": ["anuradhapura", "අනුරාධපුරය", "அனுராதபுரம்"],
    "vavuniya": ["vavuniya", "වවුනියාව", "வவுனியா"],
    "jaffna": ["jaffna", "යාපනය", "யாழ்ப்பாணம்"],
    "avissawella": ["avissawella", "අවිස්සාවේල්ල", "அவிசாவளை"],
    "peradeniya": ["peradeniya", "පේරාදෙණිය", "பேராதனை"],
    "polgahawela": ["polgahawela", "පොල්ගහවෙල", "பொல்கஹவெல"],
}


def normalize_station(station_name: str) -> str:
    """Normalize input station name to canonical station name."""
    clean = station_name.strip().lower()
    for canonical, aliases in STATION_ALIASES.items():
        for a in aliases:
            if clean == a or (len(a) > 4 and a in clean):
                return " ".join(w.capitalize() for w in canonical.split())
    return " ".join(w.capitalize() for w in station_name.strip().split())


def stations_match(station_a: str, station_b: str) -> bool:
    """Case-insensitive and alias-aware station equality check."""
    norm_a = normalize_station(station_a).lower()
    norm_b = normalize_station(station_b).lower()
    if norm_a == norm_b:
        return True
    # Colombo, Colombo Fort, and Maradana match interchangeably for terminal city travel
    colombo_set = {"colombo", "colombo fort", "maradana"}
    if norm_a in colombo_set and norm_b in colombo_set:
        return True
    return False


# ---------------------------------------------------------------------------
# Daily Services Catalog (from schedules.md + canonical project fixtures)
# ---------------------------------------------------------------------------
DAILY_SERVICES: list[DailyService] = [
    # 1. Podi Menike (1005): Colombo Fort -> Badulla (via Kandy, Nanu Oya, Ella)
    DailyService(
        service_id="1005-COLOMBO-BADULLA",
        train_id="1005",
        train_name="Podi Menike Express",
        origin_station="Colombo Fort",
        destination_station="Badulla",
        route="Colombo Fort - Badulla",
        departure_time=time(5, 55),
        arrival_time=time(16, 35),
        is_overnight=False,
        first_class_capacity=40,
        second_class_capacity=120,
        stops=(
            ServiceStop("Colombo Fort", None, time(5, 55), day_offset=0),
            ServiceStop("Polgahawela", time(7, 20), time(7, 25), day_offset=0),
            ServiceStop("Peradeniya", time(8, 35), time(8, 40), day_offset=0),
            ServiceStop("Kandy", time(8, 47), time(8, 55), day_offset=0),
            ServiceStop("Nanu Oya", time(12, 45), time(12, 50), day_offset=0),
            ServiceStop("Ella", time(15, 30), time(15, 35), day_offset=0),
            ServiceStop("Badulla", time(16, 35), None, day_offset=0),
        ),
    ),

    # 2. Podi Menike Return (1010): Kandy -> Colombo Fort
    DailyService(
        service_id="1010-KANDY-COLOMBO",
        train_id="1010",
        train_name="Podi Menike (Return)",
        origin_station="Kandy",
        destination_station="Colombo Fort",
        route="Kandy - Colombo Fort",
        departure_time=time(14, 35),
        arrival_time=time(17, 20),
        is_overnight=False,
        first_class_capacity=40,
        second_class_capacity=120,
        stops=(
            ServiceStop("Kandy", None, time(14, 35), day_offset=0),
            ServiceStop("Peradeniya", time(14, 45), time(14, 48), day_offset=0),
            ServiceStop("Polgahawela", time(15, 55), time(16, 0), day_offset=0),
            ServiceStop("Colombo Fort", time(17, 20), None, day_offset=0),
        ),
    ),

    # 3. Udarata Menike (1015): Colombo Fort -> Badulla (via Kandy, Nanu Oya, Ella)
    DailyService(
        service_id="1015-COLOMBO-BADULLA",
        train_id="1015",
        train_name="Udarata Menike Express",
        origin_station="Colombo Fort",
        destination_station="Badulla",
        route="Colombo Fort - Badulla",
        departure_time=time(8, 30),
        arrival_time=time(19, 15),
        is_overnight=False,
        first_class_capacity=30,
        second_class_capacity=140,
        stops=(
            ServiceStop("Colombo Fort", None, time(8, 30), day_offset=0),
            ServiceStop("Polgahawela", time(9, 50), time(9, 55), day_offset=0),
            ServiceStop("Peradeniya", time(11, 25), time(11, 30), day_offset=0),
            ServiceStop("Kandy", time(11, 40), time(11, 48), day_offset=0),
            ServiceStop("Nanu Oya", time(15, 20), time(15, 25), day_offset=0),
            ServiceStop("Ella", time(18, 10), time(18, 15), day_offset=0),
            ServiceStop("Badulla", time(19, 15), None, day_offset=0),
        ),
    ),

    # 4. Intercity Express (1020): Colombo Fort -> Kandy
    DailyService(
        service_id="1020-COLOMBO-KANDY",
        train_id="1020",
        train_name="Intercity Express",
        origin_station="Colombo Fort",
        destination_station="Kandy",
        route="Colombo Fort - Kandy",
        departure_time=time(15, 35),
        arrival_time=time(18, 10),
        is_overnight=False,
        first_class_capacity=40,
        second_class_capacity=120,
        stops=(
            ServiceStop("Colombo Fort", None, time(15, 35), day_offset=0),
            ServiceStop("Polgahawela", time(16, 45), time(16, 48), day_offset=0),
            ServiceStop("Peradeniya", time(17, 55), time(17, 58), day_offset=0),
            ServiceStop("Kandy", time(18, 10), None, day_offset=0),
        ),
    ),

    # 5. Ruhunu Kumari (50): Maradana / Colombo Fort -> Matara (via Galle)
    DailyService(
        service_id="50-COLOMBO-MATARA",
        train_id="50",
        train_name="Ruhunu Kumari",
        origin_station="Colombo Fort",
        destination_station="Matara",
        route="Colombo Fort - Matara",
        departure_time=time(5, 50),
        arrival_time=time(9, 10),
        is_overnight=False,
        first_class_capacity=40,
        second_class_capacity=120,
        stops=(
            ServiceStop("Colombo Fort", None, time(5, 50), day_offset=0),
            ServiceStop("Galle", time(8, 15), time(8, 22), day_offset=0),
            ServiceStop("Matara", time(9, 10), None, day_offset=0),
        ),
    ),

    # 6. Sagarika (55): Colombo Fort -> Galle
    DailyService(
        service_id="55-COLOMBO-GALLE",
        train_id="55",
        train_name="Sagarika Express",
        origin_station="Colombo Fort",
        destination_station="Galle",
        route="Colombo Fort - Galle",
        departure_time=time(15, 20),
        arrival_time=time(17, 35),
        is_overnight=False,
        first_class_capacity=40,
        second_class_capacity=120,
        stops=(
            ServiceStop("Colombo Fort", None, time(15, 20), day_offset=0),
            ServiceStop("Galle", time(17, 35), None, day_offset=0),
        ),
    ),

    # 7. Express (60): Colombo Fort -> Matara (via Galle)
    DailyService(
        service_id="60-COLOMBO-MATARA",
        train_id="60",
        train_name="Coastal Express",
        origin_station="Colombo Fort",
        destination_station="Matara",
        route="Colombo Fort - Matara",
        departure_time=time(18, 0),
        arrival_time=time(21, 5),
        is_overnight=False,
        first_class_capacity=40,
        second_class_capacity=120,
        stops=(
            ServiceStop("Colombo Fort", None, time(18, 0), day_offset=0),
            ServiceStop("Galle", time(20, 15), time(20, 20), day_offset=0),
            ServiceStop("Matara", time(21, 5), None, day_offset=0),
        ),
    ),

    # 8. Yal Devi (4085): Colombo Fort -> Jaffna
    DailyService(
        service_id="4085-COLOMBO-JAFFNA",
        train_id="4085",
        train_name="Yal Devi Express",
        origin_station="Colombo Fort",
        destination_station="Jaffna",
        route="Colombo Fort - Jaffna",
        departure_time=time(5, 45),
        arrival_time=time(13, 20),
        is_overnight=False,
        first_class_capacity=45,
        second_class_capacity=150,
        stops=(
            ServiceStop("Colombo Fort", None, time(5, 45), day_offset=0),
            ServiceStop("Kurunegala", time(7, 30), time(7, 35), day_offset=0),
            ServiceStop("Anuradhapura", time(9, 40), time(9, 48), day_offset=0),
            ServiceStop("Vavuniya", time(10, 55), time(11, 2), day_offset=0),
            ServiceStop("Jaffna", time(13, 20), None, day_offset=0),
        ),
    ),

    # 9. Uttara Devi (4095): Colombo Fort -> Jaffna (Overnight service)
    DailyService(
        service_id="4095-COLOMBO-JAFFNA",
        train_id="4095",
        train_name="Uttara Devi (Overnight)",
        origin_station="Colombo Fort",
        destination_station="Jaffna",
        route="Colombo Fort - Jaffna",
        departure_time=time(20, 15),
        arrival_time=time(4, 10),
        is_overnight=True,
        first_class_capacity=40,
        second_class_capacity=120,
        stops=(
            ServiceStop("Colombo Fort", None, time(20, 15), day_offset=0),
            ServiceStop("Kurunegala", time(22, 0), time(22, 5), day_offset=0),
            ServiceStop("Anuradhapura", time(0, 15), time(0, 22), day_offset=1),
            ServiceStop("Vavuniya", time(1, 45), time(1, 52), day_offset=1),
            ServiceStop("Jaffna", time(4, 10), None, day_offset=1),
        ),
    ),

    # 10. Rajarata Rejini (4025): Colombo Fort -> Anuradhapura
    DailyService(
        service_id="4025-COLOMBO-ANURADHAPURA",
        train_id="4025",
        train_name="Rajarata Rejini",
        origin_station="Colombo Fort",
        destination_station="Anuradhapura",
        route="Colombo Fort - Anuradhapura",
        departure_time=time(6, 35),
        arrival_time=time(10, 50),
        is_overnight=False,
        first_class_capacity=40,
        second_class_capacity=120,
        stops=(
            ServiceStop("Colombo Fort", None, time(6, 35), day_offset=0),
            ServiceStop("Kurunegala", time(8, 20), time(8, 25), day_offset=0),
            ServiceStop("Anuradhapura", time(10, 50), None, day_offset=0),
        ),
    ),

    # 11. Local Commuter Morning (2210): Colombo Fort -> Avissawella
    DailyService(
        service_id="2210-COLOMBO-AVISSAWELLA",
        train_id="2210",
        train_name="Kelani Valley Commuter",
        origin_station="Colombo Fort",
        destination_station="Avissawella",
        route="Colombo Fort - Avissawella",
        departure_time=time(6, 10),
        arrival_time=time(7, 40),
        is_overnight=False,
        first_class_capacity=0,
        second_class_capacity=120,
        stops=(
            ServiceStop("Colombo Fort", None, time(6, 10), day_offset=0),
            ServiceStop("Avissawella", time(7, 40), None, day_offset=0),
        ),
    ),

    # 12. Local Commuter Evening (2230): Colombo Fort -> Avissawella
    DailyService(
        service_id="2230-COLOMBO-AVISSAWELLA",
        train_id="2230",
        train_name="Kelani Valley Commuter",
        origin_station="Colombo Fort",
        destination_station="Avissawella",
        route="Colombo Fort - Avissawella",
        departure_time=time(17, 5),
        arrival_time=time(18, 35),
        is_overnight=False,
        first_class_capacity=0,
        second_class_capacity=120,
        stops=(
            ServiceStop("Colombo Fort", None, time(17, 5), day_offset=0),
            ServiceStop("Avissawella", time(18, 35), None, day_offset=0),
        ),
    ),
]


def find_matching_services(
    origin: str | None = None,
    destination: str | None = None,
    train_id: str | None = None,
) -> list[tuple[DailyService, ServiceStop | None, ServiceStop | None]]:
    """
    Search daily services that match origin, destination, or train_id.
    Enforces route station order: origin must appear BEFORE destination in stop sequence.
    Returns list of (service, origin_stop, destination_stop).
    """
    results: list[tuple[DailyService, ServiceStop | None, ServiceStop | None]] = []

    for svc in DAILY_SERVICES:
        if train_id and svc.train_id.strip().upper() != train_id.strip().upper():
            continue

        if not origin and not destination:
            results.append((svc, svc.stops[0], svc.stops[-1]))
            continue

        origin_match: tuple[int, ServiceStop] | None = None
        dest_match: tuple[int, ServiceStop] | None = None

        for idx, stop in enumerate(svc.stops):
            if origin and origin_match is None and stations_match(stop.station, origin):
                origin_match = (idx, stop)
            if destination and dest_match is None and stations_match(stop.station, destination):
                dest_match = (idx, stop)

        # Both origin and destination provided
        if origin and destination:
            if origin_match and dest_match and origin_match[0] < dest_match[0]:
                results.append((svc, origin_match[1], dest_match[1]))
        elif origin:
            if origin_match and origin_match[0] < len(svc.stops) - 1:
                results.append((svc, origin_match[1], svc.stops[-1]))
        elif destination:
            if dest_match and dest_match[0] > 0:
                results.append((svc, svc.stops[0], dest_match[1]))

    return results


def get_service_by_id(service_id: str) -> DailyService | None:
    """Find a DailyService definition by its unique service_id."""
    clean = service_id.strip().upper()
    for svc in DAILY_SERVICES:
        if svc.service_id.upper() == clean:
            return svc
    return None


def get_service_by_train_id(train_id: str) -> DailyService | None:
    """Find a DailyService definition by its train_id."""
    clean = train_id.strip().upper()
    for svc in DAILY_SERVICES:
        if svc.train_id.upper() == clean:
            return svc
    return None
