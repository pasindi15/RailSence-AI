"""Free-text passenger questions with no train pre-selected (the Choo assistant).

The popup already knows which train it is about; a chat message doesn't. This
module does the NLP needed to turn one sentence into a structured query:

* intent        - passenger_answer.detect_intent() plus a "find trains" check
                  ("is there any train to Polonnaruwa after 19:15?").
* time          - "after 19.15pm", "before 8am", "tonight", "this morning".
* date          - today / tomorrow.
* stations      - every station mentioned, with its role: destination
                  ("to / go / for / reach X") or origin ("from / leaving X").
                  Exact n-gram match first, then fuzzy (typos like "polonaruwa").
* train         - an operational id (DM-8055), a service number (4085) or a
                  service name ("night mail"), matched against today's board.

Everything is deterministic; the caller (main.passenger_query) answers from
the live board, the live journey and verified incidents.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import time as dtime
from typing import Any, Optional

from nlp import passenger_answer

_TIME = r"(\d{1,2})(?:\s*[.:]\s*(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?"
_AFTER = re.compile(rf"\b(?:after|from|past|later than|since|at or after)\s+{_TIME}(?![\w-])", re.I)
_BEFORE = re.compile(rf"\b(?:before|by|until|till|earlier than)\s+{_TIME}(?![\w-])", re.I)
_AT = re.compile(rf"\b(?:at|around)\s+{_TIME}(?![\w-])", re.I)
_TRAIN_ID = re.compile(r"\b([A-Za-z]{2,12}-\d{3,5})\b")
_TRAIN_NUMBER = re.compile(r"\b(?:train|no\.?|number|service|#)\s*#?\s*(\d{2,5})\b", re.I)

_DEST_CUES = ("to", "go", "go to", "goes to", "going to", "for", "towards", "reach", "reaches", "get to",
              "arrive at", "arrive in", "arriving at", "into", "till", "bound for", "heading to")
_ORIGIN_CUES = ("from", "leaving", "leave", "departing", "depart", "starting at", "board at", "boarding at")
_FIND_CUES = ("any train", "any trains", "trains", "is there a train", "is there any", "available", "next train",
              "which train", "what train", "train to", "trains to", "train from", "services", "options",
              "can i go", "can i get", "how can i go", "how do i get", "train going", "train for")
_OVERVIEW_DELAY = ("which trains are delayed", "delayed trains", "any delays", "trains delayed", "late trains",
                   "trains running late", "any train delayed", "all delays", "delays today")
_STOPWORDS_NAME = {"express", "train", "the", "menike", "intercity"}


@dataclass
class ParsedQuery:
    text: str
    intent: str
    find_trains: bool = False
    delay_overview: bool = False
    after: Optional[dtime] = None
    before: Optional[dtime] = None
    day_offset: int = 0
    origin: Optional[str] = None
    destination: Optional[str] = None
    stations: list[str] = field(default_factory=list)
    train_id: Optional[str] = None
    train_number: Optional[str] = None
    train_name_matches: list[str] = field(default_factory=list)  # train_ids whose name was mentioned


def _to_time(hh: str, mm: Optional[str], ampm: Optional[str]) -> Optional[dtime]:
    h, m = int(hh), int(mm or 0)
    marker = (ampm or "").replace(".", "").lower()
    if marker == "pm" and h < 12:
        h += 12
    elif marker == "am" and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return dtime(h, m)


def _parse_time(text: str) -> tuple[Optional[dtime], Optional[dtime]]:
    after = before = None
    if m := _AFTER.search(text):
        after = _to_time(*m.groups())
    if m := _BEFORE.search(text):
        before = _to_time(*m.groups())
    if after is None and before is None and (m := _AT.search(text)):
        # "at 7pm" -> a window around that time
        t = _to_time(*m.groups())
        if t is not None:
            after = dtime(max(0, t.hour - 1), t.minute)
            before = dtime(min(23, t.hour + 1), t.minute)
    low = text.casefold()
    if after is None and before is None:
        if "morning" in low:
            after, before = dtime(0, 0), dtime(12, 0)
        elif "afternoon" in low:
            after, before = dtime(12, 0), dtime(17, 0)
        elif "evening" in low:
            after = dtime(17, 0)
        elif "tonight" in low or "night train" in low:
            after = dtime(18, 0)
    return after, before


def _station_mentions(text: str, names: list[str]) -> list[tuple[int, str]]:
    """(word position, station) for every station named in the text."""
    words = re.sub(r"[^\w\s-]", " ", text.casefold()).split()
    by_fold = {n.casefold(): n for n in names}
    by_fold.setdefault("colombo", "Colombo Fort")
    by_fold.setdefault("fort", "Colombo Fort")
    found: list[tuple[int, str]] = []
    used: set[int] = set()
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            if any(k in used for k in range(i, i + n)):
                continue
            gram = " ".join(words[i:i + n])
            name = by_fold.get(gram)
            if name is None and len(gram) >= 5:
                close = difflib.get_close_matches(gram, list(by_fold), n=1, cutoff=0.84)
                name = by_fold[close[0]] if close else None
            if name and name not in [f[1] for f in found]:
                found.append((i, name))
                used.update(range(i, i + n))
    return sorted(found)


def _role(words: list[str], pos: int) -> Optional[str]:
    before = " " + " ".join(words[max(0, pos - 3):pos])
    for cue in sorted(_ORIGIN_CUES, key=len, reverse=True):
        if before.endswith(" " + cue):
            return "origin"
    for cue in sorted(_DEST_CUES, key=len, reverse=True):
        if before.endswith(" " + cue):
            return "destination"
    return None


def _name_matches(text: str, board: list[dict[str, Any]]) -> list[str]:
    """Train ids whose service name the passenger typed (fuzzy, word-set)."""
    low = re.sub(r"[^\w\s]", " ", text.casefold())
    words = low.split()
    hits: list[str] = []
    for row in board:
        name = str(row.get("train_name") or "").strip()
        if not name or name.lower().startswith("historical"):
            continue
        key_words = [w for w in re.sub(r"[^\w\s]", " ", name.casefold()).split() if w not in _STOPWORDS_NAME]
        if not key_words:
            key_words = name.casefold().split()
        ok = True
        for kw in key_words:
            if kw in words:
                continue
            if not difflib.get_close_matches(kw, words, n=1, cutoff=0.8):
                ok = False
                break
        if ok and row.get("train_id") not in hits:
            hits.append(str(row.get("train_id")))
    return hits


def parse(text: str, station_names: list[str], board: list[dict[str, Any]]) -> ParsedQuery:
    low = f" {text.casefold()} "
    after, before = _parse_time(text)
    q = ParsedQuery(text=text, intent=passenger_answer.detect_intent(text, default="status"),
                    after=after, before=before)
    if "tomorrow" in low:
        q.day_offset = 1

    if m := _TRAIN_ID.search(text):
        q.train_id = m.group(1).upper()
    elif m := _TRAIN_NUMBER.search(text):
        q.train_number = m.group(1)
    else:
        board_ids = {str(r.get("train_id")) for r in board}
        for tok in re.findall(r"(?<![\d.:])(\d{2,5})(?![\d.:]|\s*(?:am|pm|a\.m|p\.m))", text, re.I):
            if tok in board_ids:
                q.train_number = tok
                break
    q.train_name_matches = _name_matches(text, board) if not (q.train_id or q.train_number) else []

    words = re.sub(r"[^\w\s-]", " ", text.casefold()).split()
    mentions = _station_mentions(text, station_names)
    q.stations = [name for _, name in mentions]
    for pos, name in mentions:
        role = _role(words, pos)
        if role == "origin" and not q.origin:
            q.origin = name
        elif role == "destination" and not q.destination:
            q.destination = name
    unassigned = [n for n in q.stations if n not in (q.origin, q.destination)]
    if len(q.stations) >= 2 and not q.origin and not q.destination:
        q.origin, q.destination = q.stations[0], q.stations[1]  # "Colombo Kandy trains"
    elif unassigned and q.origin and not q.destination:
        q.destination = unassigned[0]
    elif unassigned and q.destination and not q.origin:
        q.origin = unassigned[0]

    has_train = bool(q.train_id or q.train_number or q.train_name_matches)
    q.delay_overview = not has_train and any(c in low for c in _OVERVIEW_DELAY)
    q.find_trains = (not has_train and not q.delay_overview and q.intent not in ("incidents", "handoff")
                     and bool(q.stations or after or before) and
                     (any(c in low for c in _FIND_CUES) or q.destination is not None or q.origin is not None
                      or q.intent in ("departure", "eta", "stops", "status")))
    return q
