"""
NER on technician free-text notes.
Extracts: component names, part numbers, dates mentioned.
"""

import re
import spacy
from typing import Optional

_nlp: Optional[spacy.language.Language] = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        try:
            _nlp = spacy.load("en_core_web_sm")
        except OSError:
            _nlp = spacy.blank("en")
    return _nlp


COMPONENT_PATTERNS = re.compile(
    r"\b(brake|braking system|engine|bogie|wheel|axle|pantograph|compressor|"
    r"gearbox|coupling|suspension|door mechanism|air conditioning|hvac|"
    r"traction motor|transformer|circuit breaker)\b",
    re.IGNORECASE,
)

PART_NUMBER_PATTERN = re.compile(r"\b([A-Z]{1,4}-?\d{3,8})\b")


def extract_entities(text: str) -> dict:
    if not text.strip():
        return {"components": [], "part_numbers": [], "dates": [], "raw_ents": []}

    nlp = _get_nlp()
    doc = nlp(text)

    components = list(set(m.group().lower() for m in COMPONENT_PATTERNS.finditer(text)))
    part_numbers = list(set(PART_NUMBER_PATTERN.findall(text)))
    dates = [ent.text for ent in doc.ents if ent.label_ in ("DATE", "TIME")]
    raw_ents = [{"text": ent.text, "label": ent.label_} for ent in doc.ents]

    return {
        "components": components,
        "part_numbers": part_numbers,
        "dates": dates,
        "raw_ents": raw_ents,
    }
