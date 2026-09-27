"""Live journey tracking and the passenger answers built on it."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import incident_map  # noqa: E402
import live_tracker  # noqa: E402
from nlp import passenger_answer  # noqa: E402

TZ = live_tracker.LOCAL_TZ
STATIONS = live_tracker.StationIndex(incident_map.STATION_LOCATIONS)

NIGHT_MAIL = {
    "train_id": "DM-8055", "train_name": "Night Mail", "route": "Colombo Fort - Batticaloa",
    "from_station": "Colombo Fort", "to_station": "Batticaloa",
    "departure_time": "19:15:00", "arrival_time": "04:30:00",
    "stops": ["Colombo Fort", "Ragama", "Polgahawela", "Kurunegala", "Maho", "Habarana", "Batticaloa"],
}
KANDY_IC = {
    "train_id": "IC-1001", "train_name": "Intercity Express", "route": "Colombo Fort - Kandy",
    "from_station": "Colombo Fort", "to_station": "Kandy",
    "departure_time": "16:35:00", "arrival_time": "19:40:00",
    "stops": ["Colombo Fort", "Ragama", "Gampaha", "Polgahawela", "Peradeniya", "Kandy"],
}


def at(hh, mm, day=27):
    return datetime(2026, 9, day, hh, mm, tzinfo=TZ)


def no_impact(_inc, _label):
    return {"minutes": 0}


def fixed_impact(minutes):
    return lambda _inc, _label: {"minutes": minutes, "samples": 5, "basis": "5 similar past incidents"}


def test_overnight_train_is_not_arrived_before_departure():
    # The reported bug: at 18:52 a 19:15 -> 04:30 service showed "ARRIVED".
    live = live_tracker.compute_live(NIGHT_MAIL, STATIONS, [], no_impact, now=at(18, 52))
    assert live["status"] == "SCHEDULED"
    assert live["departs_at"] == "19:15"
    assert live["minutes_to_next"] == 23
    assert live["expected_arrival"] == "04:30 (+1)"


def test_overnight_train_in_transit_after_midnight_uses_last_nights_run():
    live = live_tracker.compute_live(NIGHT_MAIL, STATIONS, [], no_impact, now=at(2, 0))
    assert live["status"] in ("IN_TRANSIT", "AT_STATION")
    assert live["service_day"] == "yesterday"
    assert 50 < live["progress_percent"] < 100


def test_overnight_train_arrived_in_the_morning_then_scheduled_again():
    assert live_tracker.compute_live(NIGHT_MAIL, STATIONS, [], no_impact, now=at(4, 40))["status"] == "SCHEDULED"


def test_intermediate_stations_get_ordered_times_between_departure_and_arrival():
    live = live_tracker.compute_live(KANDY_IC, STATIONS, [], no_impact, now=at(17, 30))
    names = [r["station"] for r in live["timeline"]]
    assert names == KANDY_IC["stops"]
    times = [r["scheduled"] for r in live["timeline"]]
    assert times[0] == "16:35" and times[-1] == "19:40"
    assert times == sorted(times)
    assert live["status"] in ("IN_TRANSIT", "AT_STATION")
    assert live["last_station"] and live["next_station"]


def test_verified_incident_on_route_delays_downstream_stations_only():
    rain = {"id": "inc-1", "station": "Kandy", "incident_type": "weather", "summary": "Heavy rain at Kandy",
            "verified_at": (at(15, 0) - timedelta(hours=0)).isoformat()}
    live = live_tracker.compute_live(KANDY_IC, STATIONS, [rain], fixed_impact(16), now=at(17, 30))
    rows = {r["station"]: r for r in live["timeline"]}
    assert rows["Peradeniya"]["delay_minutes"] == 0
    assert rows["Kandy"]["delay_minutes"] == 16
    assert rows["Kandy"]["reasons"] == ["inc-1"]
    assert live["expected_arrival"] == "19:56"
    assert live["disruptions"][0]["affects_this_run"] is True


def test_incident_off_this_trains_line_is_ignored():
    galle = {"id": "inc-2", "station": "Galle", "incident_type": "signal_fault", "verified_at": at(15, 0).isoformat()}
    live = live_tracker.compute_live(KANDY_IC, STATIONS, [galle], fixed_impact(14), now=at(17, 30))
    assert live["disruptions"] == [] and live["delay_minutes"] == 0


def test_incident_at_unlisted_corridor_station_is_placed_between_stops():
    # Kurunegala is on the Batticaloa line; a board without Kurunegala still gets it.
    ctx = {**NIGHT_MAIL, "stops": ["Colombo Fort", "Polgahawela", "Maho", "Batticaloa"]}
    inc = {"id": "inc-3", "station": "Kurunegala", "incident_type": "track_obstruction",
           "verified_at": at(18, 0).isoformat()}
    live = live_tracker.compute_live(ctx, STATIONS, [inc], fixed_impact(17), now=at(18, 52))
    d = live["disruptions"][0]
    assert (d["after"], d["before"]) == ("Polgahawela", "Maho")
    assert live["delay_minutes"] == 17


def test_incident_reported_after_train_passed_does_not_delay_that_run():
    inc = {"id": "inc-4", "station": "Ragama", "incident_type": "signal_fault", "verified_at": at(19, 0).isoformat()}
    live = live_tracker.compute_live(KANDY_IC, STATIONS, [inc], fixed_impact(14), now=at(19, 10))
    assert live["disruptions"][0]["affects_this_run"] is False
    assert live["delay_minutes"] == 0


def test_station_entity_extraction_handles_typos():
    names = KANDY_IC["stops"]
    assert live_tracker.find_station_mention("when will it reach kandy?", names, STATIONS) == "Kandy"
    assert live_tracker.find_station_mention("time at polgahawla", names, STATIONS) == "Polgahawela"
    assert live_tracker.find_station_mention("is this train delayed", names, STATIONS) is None


def test_intent_fallback_and_rain_not_matching_train():
    assert passenger_answer.detect_intent("Is this train delayed?") == "delay"
    assert passenger_answer.detect_intent("wher is it") == "location"
    assert passenger_answer.detect_intent("show the timetable") == "stops"
    assert passenger_answer.detect_intent("book a seat on a late train") == "handoff"


def test_answer_for_scheduled_overnight_train_says_not_departed():
    live = live_tracker.compute_live(NIGHT_MAIL, STATIONS, [], no_impact, now=at(18, 52))
    ans = passenger_answer.compose_answer("delay", NIGHT_MAIL, {"minutes": 0, "confidence": "medium"}, [], [],
                                          live=live)
    text = " ".join(ans["paragraphs"])
    assert "arrived" not in ans["headline"].lower() and "hasn't left yet" in text
    assert ans["live"]["status"] == "SCHEDULED"


def test_station_question_reports_delayed_time_and_reason():
    rain = {"id": "inc-1", "station": "Kandy", "incident_type": "weather", "summary": "Heavy rain at Kandy",
            "verified_at": at(15, 0).isoformat()}
    live = live_tracker.compute_live(KANDY_IC, STATIONS, [rain], fixed_impact(16), now=at(17, 30))
    ans = passenger_answer.compose_answer("eta", KANDY_IC, None, [], [], live=live, station="Kandy")
    assert ans["intent"] == "station"
    assert ans["headline"] == "Expected at Kandy around 19:56"
    assert any("bad weather" in p for p in ans["paragraphs"])
