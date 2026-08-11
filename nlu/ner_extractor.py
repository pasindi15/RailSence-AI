"""
nlu/ner_extractor.py
Phase 1: stub — returns an empty entity dict so callers can be written
against the real return shape now.
Phase 2: load spaCy (en_core_web_sm + custom station-name patterns) here
and extract route, station, date/time entities.
"""

from typing import TypedDict, Optional


class ExtractedEntities(TypedDict):
    route: Optional[str]
    station: Optional[str]
    train_id: Optional[str]
    date_time: Optional[str]


def extract_entities(message: str) -> ExtractedEntities:
    # Phase 2 TODO: replace with real spaCy NER + custom station gazetteer
    return ExtractedEntities(route=None, station=None, train_id=None, date_time=None)
