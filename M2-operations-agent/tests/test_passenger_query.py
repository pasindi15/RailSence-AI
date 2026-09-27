"""NLP parsing of free-text passenger chat questions (nlp/passenger_query.py)."""

import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import incident_map  # noqa: E402
import live_tracker  # noqa: E402
from nlp import passenger_query as pq  # noqa: E402

NAMES = live_tracker.StationIndex(incident_map.STATION_LOCATIONS).names()
BOARD = [
    {"train_id": "DM-8055", "train_name": "Night Mail"},
    {"train_id": "PM-8056", "train_name": "Podi Menike"},
    {"train_id": "4085", "train_name": "Yal Devi Express"},
    {"train_id": "YD-9337", "train_name": "Historical YD-9337"},
]


def test_reported_question_is_a_journey_search_with_time_and_destination():
    q = pq.parse("after 19.15pm is ther any train available to go polonnaruwa", NAMES, BOARD)
    assert q.find_trains
    assert q.destination == "Polonnaruwa" and q.origin is None
    assert q.after == time(19, 15)


def test_origin_destination_roles_and_12h_clock():
    q = pq.parse("trains from kandy to colombo fort before 3pm", NAMES, BOARD)
    assert (q.origin, q.destination) == ("Kandy", "Colombo Fort")
    assert q.before == time(15, 0)


def test_train_by_name_id_and_number():
    assert pq.parse("where is the night mail now?", NAMES, BOARD).train_name_matches == ["DM-8055"]
    assert pq.parse("when will DM-8055 reach Kurunegala?", NAMES, BOARD).train_id == "DM-8055"
    assert pq.parse("is 4085 late", NAMES, BOARD).train_number == "4085"
    # a time is never mistaken for a train number
    assert pq.parse("any train after 19.15", NAMES, BOARD).train_number is None


def test_station_typo_and_tomorrow():
    q = pq.parse("trains to polonaruwa tomorrow morning", NAMES, BOARD)
    assert q.destination == "Polonnaruwa" and q.day_offset == 1
    assert (q.after, q.before) == (time(0, 0), time(12, 0))


def test_overview_and_incident_questions_are_not_journey_searches():
    assert pq.parse("which trains are delayed?", NAMES, BOARD).delay_overview
    q = pq.parse("any incidents on the kandy line today?", NAMES, BOARD)
    assert q.intent == "incidents" and not q.find_trains
