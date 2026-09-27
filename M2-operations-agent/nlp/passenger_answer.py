"""Passenger-facing operations answers for the user portal's train popup.

Three NLP steps, all deterministic so every sentence can be traced back to data:

1. detect_intent()  - intent classification of a free-text passenger question.
                      Weighted keyword rules first; when no rule fires (typos,
                      unusual wording) a TF-IDF character n-gram classifier
                      picks the nearest labelled example question.
2. Station entity   - live_tracker.find_station_mention() pulls the station a
                      passenger asks about ("when does it reach Kandy?").
3. compose_answer() - template natural-language generation over the live
                      journey (live_tracker.compute_live), the delay model,
                      verified map incidents and retrieved incident precedent.

Nothing here invents a cause or a number: if a value is missing the answer
says so plainly instead of guessing.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Optional

# Ordered keyword rules. Each hit adds weight; the highest score wins.
_INTENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("handoff", ("book", "ticket", "fare", "price", "cost", "refund", "cancel", "seat", "reserve", "payment")),
    ("greeting", ("hello", "hi ", "hey", "thank", "thanks", "good morning", "good evening")),
    ("reason", ("why", "reason", "cause", "because", "what happened")),
    ("eta", ("arrive", "arrival", "reach", "get to", " eta ", "when will", "what time", "how long")),
    ("departure", ("depart", "leave", "leaving", "departure", "start", "set off")),
    ("location", ("where", "location", "position", "which station", "how far", "progress", "right now",
                  "currently", "now at", "passed", "track")),
    ("maintenance", ("maintenance", "safe", "fault", "breakdown", "repair", "condition", "out of service", "mechanical")),
    ("incidents", ("incident", "accident", "disruption", "problem", "issue", "alert", "block", " rain", "flood",
                   "weather")),  # " rain" so "train" never matches
    ("stops", ("stop", "stops", "stations", "via", "pass through", "route", "timetable", "schedule", "each station",
               "all station", "time table")),
    ("delay", ("delay", "late", "on time", "ontime", "behind", "running", "wait", "punctual")),
    ("status", ("status", "operation", "operational", "update", "overview", "running ok", "everything ok")),
]

# Labelled example questions for the TF-IDF fallback classifier.
_INTENT_EXAMPLES: dict[str, list[str]] = {
    "delay": ["is this train delayed", "is it late today", "is the train on time", "how late is it running",
              "any delay", "will it be late", "delayed", "delay"],
    "eta": ["when will it arrive", "what time does it reach", "arrival time", "when does it get there",
            "how long until it arrives", "eta please"],
    "departure": ["when does it leave", "departure time", "what time does it depart", "has it left yet",
                  "when does it start"],
    "location": ["where is the train now", "current location", "where is it right now", "which station is it at",
                 "how far has it gone", "live position of the train"],
    "reason": ["why is it late", "what caused the delay", "reason for the delay", "why is it delayed"],
    "incidents": ["any incidents on the line", "is there rain on the route", "any problems on the way",
                  "any alerts today", "is there flooding"],
    "maintenance": ["is the train safe", "train condition", "any breakdown", "is it under maintenance"],
    "stops": ["which stations does it stop at", "show the timetable", "list of stops", "stations on the route",
              "time at each station"],
    "status": ["what is the status", "operational status", "give me an update", "is everything ok"],
    "greeting": ["hello", "hi there", "thank you", "thanks a lot"],
}

_CAUSE_WORDS = {
    "signal_fault": "signal problems",
    "mechanical": "a mechanical fault",
    "weather": "bad weather",
    "track_obstruction": "something blocking the track",
    "staffing": "crew availability",
    "other": "an operational issue",
}

_SUGGESTIONS = {
    "delay": ["When will it arrive?", "Why might it be late?", "Where is it now?"],
    "eta": ["Is it delayed?", "Where is it now?", "Show the station timetable"],
    "location": ["When will it arrive?", "Is it delayed?", "Show the station timetable"],
    "reason": ["Is it safe to travel?", "When will it arrive?", "Any incidents on the line?"],
    "maintenance": ["Is it delayed?", "Where is it now?", "Any incidents on the line?"],
    "incidents": ["Is it delayed?", "Why might it be late?", "Show the station timetable"],
    "stops": ["Where is it now?", "When will it arrive?", "Is it delayed?"],
    "departure": ["Is it delayed?", "When will it arrive?", "Show the station timetable"],
    "status": ["Is it delayed?", "Where is it now?", "Show the station timetable"],
    "greeting": ["Is it delayed?", "Where is it now?", "When will it arrive?"],
    "station": ["Where is it now?", "Is it delayed?", "Show the station timetable"],
}

_tfidf = None  # (vectorizer, matrix, labels), built lazily


def _tfidf_intent(text: str, threshold: float = 0.32) -> Optional[str]:
    """Nearest labelled example by TF-IDF (char n-grams) cosine similarity."""
    global _tfidf
    try:
        if _tfidf is None:
            from sklearn.feature_extraction.text import TfidfVectorizer
            labels, docs = [], []
            for intent, examples in _INTENT_EXAMPLES.items():
                for ex in examples:
                    labels.append(intent)
                    docs.append(ex)
            vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
            _tfidf = (vec, vec.fit_transform(docs), labels)
        from sklearn.metrics.pairwise import cosine_similarity
        vec, matrix, labels = _tfidf
        scores = cosine_similarity(vec.transform([text]), matrix)[0]
        best = int(scores.argmax())
        return labels[best] if scores[best] >= threshold else None
    except Exception:
        return None


def detect_intent(question: str, default: str = "status") -> str:
    """Classify a passenger question into one operations intent."""
    text = f" {question.casefold().strip()} "
    text = re.sub(r"[^\w\s:-]", " ", text)
    scores: dict[str, int] = {}
    for intent, keywords in _INTENT_RULES:
        hits = sum(1 for kw in keywords if kw in text)
        if hits:
            scores[intent] = hits
    if not scores:
        return _tfidf_intent(text.strip()) or default
    # Booking/fare questions belong to the Booking Agent even when they also
    # mention "late" or "delay" (e.g. "refund for a late train").
    if "handoff" in scores:
        return "handoff"
    # "What time does it leave?" also trips the generic "what time" arrival
    # cue; an explicit departure verb should win that tie.
    if "departure" in scores:
        scores["departure"] += 1
    return max(scores.items(), key=lambda kv: kv[1])[0]


# ------------------------------------------------------------------ helpers

def _parse_clock(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def _clock(value: Optional[datetime]) -> str:
    return value.strftime("%H:%M") if value else "—"


def _delay_level(minutes: float) -> str:
    if minutes <= 2:
        return "on_time"
    if minutes <= 5:
        return "minor"
    if minutes <= 15:
        return "moderate"
    return "major"


def _delay_phrase(minutes: float) -> str:
    level = _delay_level(minutes)
    if level == "on_time":
        return "should be right on time"
    if level == "minor":
        return f"may run a little late, about **{minutes:.0f} minutes**"
    if level == "moderate":
        return f"is likely to be around **{minutes:.0f} minutes** late"
    return f"could be delayed by roughly **{minutes:.0f} minutes**"


def _confidence_phrase(confidence: str) -> str:
    return {
        "high": "This is based on this train's own recorded journeys, so it's a strong estimate.",
        "medium": "This is a solid estimate from our delay model, though conditions on the day can change it.",
        "low": "Please treat this as a rough guide; there isn't much past data for this exact situation.",
    }.get(confidence, "This is an estimate, not a live signal.")


def _cause(incident_type: Optional[str]) -> str:
    return _CAUSE_WORDS.get(str(incident_type or "other"), "an operational issue")


def _train_label(ctx: dict[str, Any]) -> str:
    name, tid = ctx.get("train_name"), ctx.get("train_id")
    if name and tid:
        return f"**{name}** ({tid})"
    return f"**{name or tid or 'This train'}**"


def _in_minutes(n: Optional[int]) -> str:
    if n is None:
        return ""
    if n <= 0:
        return " (any moment now)"
    if n < 60:
        return f" (in {n} min)"
    return f" (in {n // 60} h {n % 60:02d} min)"


def _position_sentence(ctx: dict[str, Any], live: Optional[dict[str, Any]] = None) -> str:
    """Where the train is, from the server-side live journey when available."""
    if live:
        status = live["status"]
        origin = live["timeline"][0]["station"]
        dest = live["timeline"][-1]["station"]
        if status == "SCHEDULED":
            return (f"It hasn't left yet. It's due to depart **{origin}** at **{live['departs_at']}**"
                    f"{_in_minutes(live.get('minutes_to_next'))}. It's {live['now']} now.")
        if status == "ARRIVED":
            return f"It has completed today's journey and reached **{dest}** at **{live['expected_arrival']}**."
        if status == "AT_STATION":
            nxt = live.get("next_station")
            tail = f" Next stop: **{nxt}**." if nxt and nxt != live["at_station"] else ""
            return f"It's at **{live['at_station']}** right now ({live['now']}).{tail}"
        nxt_row = next((r for r in live["timeline"] if r["station"] == live.get("next_station")), None)
        due = f", due there around **{nxt_row['expected']}**{_in_minutes(live.get('minutes_to_next'))}" if nxt_row else ""
        return (f"Right now ({live['now']}) it's travelling between **{live['last_station']}** and "
                f"**{live['next_station']}**{due}. That's about **{live['progress_percent']}%** of the journey.")

    live_status = str(ctx.get("live_status") or "").upper()
    current, nxt = ctx.get("current_station"), ctx.get("next_station")
    progress = ctx.get("progress_percent")
    origin, dest = ctx.get("from_station") or "its origin", ctx.get("to_station") or "its destination"
    if live_status == "ARRIVED":
        return f"It has already completed today's journey and arrived at **{current or dest}**."
    if current and nxt:
        pct = f" It's about **{progress:.0f}%** of the way there." if progress is not None else ""
        return f"Right now it's travelling between **{current}** and **{nxt}**.{pct}"
    if live_status == "IN_TRANSIT":
        pct = f", roughly **{progress:.0f}%** of the way" if progress is not None else ""
        return f"It's on its way to {dest}{pct}."
    if live_status == "SCHEDULED":
        return f"It hasn't left yet; it's due to depart **{origin}** at **{_clock(_parse_clock(ctx.get('departure_time')))}**."
    return "I don't have a live position for it at the moment."


def _disruption_sentences(live: Optional[dict[str, Any]], only_this_run: bool = True) -> list[str]:
    out = []
    for d in (live or {}).get("disruptions", []):
        if only_this_run and not d.get("affects_this_run"):
            continue
        where = (f"at **{d['station']}**" if d["on"] == "station"
                 else f"near **{d['station']}** (between {d['after']} and {d['before']})")
        basis = f" Estimate from {d['basis']}." if d.get("basis") else ""
        summary = f" “{d['summary']}”" if d.get("summary") else ""
        out.append(f"⚠️ {_cause(d.get('incident_type')).capitalize()} reported {where} today is expected "
                   f"to add about **{d['delay_minutes']:.0f} min** to every stop after it.{summary}{basis}")
    return out


def _timeline_view(live: Optional[dict[str, Any]]) -> Optional[list[dict[str, Any]]]:
    if not live:
        return None
    reason_by_id = {d["id"]: d for d in live.get("disruptions", [])}
    rows = []
    for r in live["timeline"]:
        causes = [f"{_cause(reason_by_id[i]['incident_type'])} near {reason_by_id[i]['station']}"
                  for i in r["reasons"] if i in reason_by_id]
        rows.append({"station": r["station"], "scheduled": r["scheduled"], "expected": r["expected"],
                     "delay": r["delay_minutes"], "state": r["state"], "why": "; ".join(causes)})
    return rows


# ------------------------------------------------------------ composition

def compose_answer(
    intent: str,
    ctx: dict[str, Any],
    estimate: Optional[dict[str, Any]],
    live_incidents: list[dict[str, Any]],
    precedent: list[dict[str, Any]],
    live: Optional[dict[str, Any]] = None,
    station: Optional[str] = None,
) -> dict[str, Any]:
    """Build the popup payload: headline, friendly paragraphs, facts and chips.

    estimate: {"minutes", "confidence", "corridor", "method"} or None (typical delay)
    live_incidents: reports filed today that touch this train or its stations
    precedent: retrieved historical incidents on the same corridor
    live: live_tracker.compute_live() result (timetable + position + disruptions)
    station: a station on this train's path that the passenger named
    """
    label = _train_label(ctx)
    dest = ctx.get("to_station") or "its destination"
    maintenance = str(ctx.get("maintenance_status") or "").upper()
    out_of_service = maintenance in {"OUT_OF_SERVICE", "DECOMMISSIONED"}
    if live:
        dest = live["timeline"][-1]["station"]
        arrived = live["status"] == "ARRIVED"
        not_started = live["status"] == "SCHEDULED"
    else:
        arrived = str(ctx.get("live_status") or "").upper() == "ARRIVED"
        not_started = False

    # With a live journey the delay is the whole picture (typical running delay
    # + today's verified incidents); without it, the model's typical delay.
    if live:
        minutes: Optional[float] = float(live["delay_minutes"])
    else:
        minutes = max(0.0, float(estimate["minutes"])) if estimate else None
    level = _delay_level(minutes) if minutes is not None else None
    arrival = _parse_clock(ctx.get("arrival_time"))
    departure = _parse_clock(ctx.get("departure_time"))
    if live:
        expected_arrival_text = live["expected_arrival"]
        scheduled_arrival_text = live["scheduled_arrival"]
    else:
        expected = arrival + timedelta(minutes=round(minutes)) if arrival and minutes is not None else None
        expected_arrival_text = _clock(expected) if expected else None
        scheduled_arrival_text = _clock(arrival) if arrival else "—"
    disruption_lines = _disruption_sentences(live)

    paragraphs: list[str] = []
    headline = ""
    show_timeline = False

    if intent == "handoff":
        return {
            "intent": "handoff",
            "headline": "Let me pass that to the booking assistant",
            "paragraphs": ["Tickets, fares and refunds are handled by our booking assistant. One moment…"],
            "facts": [], "gauge": None, "suggestions": [], "sources": [], "handoff": True,
        }

    station_row = None
    if live and station:
        station_row = next((r for r in live["timeline"] if r["station"] == station), None)

    if out_of_service:
        headline = "This train isn't running right now"
        paragraphs.append(
            f"{label} has been taken out of service for maintenance, so it won't be running as scheduled. "
            "Please check the board for another service on this route, or ask me about alternatives."
        )
    elif station_row and intent not in ("reason", "incidents", "maintenance", "greeting", "stops"):
        intent = "station"
        is_origin = station_row is live["timeline"][0]
        verb = "leave" if is_origin else "reach"
        if station_row["state"] == "passed":
            headline = f"Already passed {station}"
            paragraphs.append(f"{label} {'left' if is_origin else 'passed'} **{station}** at about "
                              f"**{station_row['expected']}** (scheduled {station_row['scheduled']}).")
        elif station_row["state"] == "current":
            headline = f"At {station} now"
            paragraphs.append(f"{label} is at **{station}** right now.")
        else:
            late = station_row["delay_minutes"]
            headline = f"Expected at {station} around {station_row['expected']}"
            if late > 2:
                paragraphs.append(f"{label} should {verb} **{station}** around **{station_row['expected']}**, "
                                  f"about **{late} min** after its scheduled **{station_row['scheduled']}**.")
            else:
                paragraphs.append(f"{label} should {verb} **{station}** on time at **{station_row['scheduled']}**.")
            why = [d for d in live["disruptions"] if d["id"] in
                   next((r["reasons"] for r in live["timeline"] if r["station"] == station), [])]
            for d in why:
                paragraphs.append(f"That includes about **{d['delay_minutes']:.0f} min** for "
                                  f"{_cause(d['incident_type'])} reported near **{d['station']}**.")
        paragraphs.append(_position_sentence(ctx, live))
    elif intent == "greeting":
        headline = "Happy to help!"
        paragraphs.append(
            f"You're looking at {label} to {dest}. Ask me anything about its delay, where it is, "
            "when it'll reach a station, or why it might be late."
        )
    elif intent in ("delay", "status") or (intent == "eta" and minutes is not None):
        if minutes is None:
            headline = "I couldn't get a delay estimate"
            paragraphs.append(f"I wasn't able to estimate a delay for {label} right now. Please try again shortly.")
            paragraphs.append(_position_sentence(ctx, live))
        elif arrived:
            arrived_at = live["expected_arrival"] if live else None
            headline = f"Arrived at {dest}" + (f" at {arrived_at}" if arrived_at else "")
            paragraphs.append(_position_sentence(ctx, live))
            if live and live["delay_minutes"] > 2:
                paragraphs.append(f"It came in about **{live['delay_minutes']} min** after the scheduled "
                                  f"**{live['scheduled_arrival']}**.")
            paragraphs.extend(disruption_lines)
        else:
            headline = {
                "on_time": "Looking good: on time",
                "minor": f"Small delay possible: about {minutes:.0f} min",
                "moderate": f"Expect a delay of about {minutes:.0f} min",
                "major": f"Significant delay likely: about {minutes:.0f} min",
            }[level]
            if intent == "eta" and expected_arrival_text:
                headline = f"Expected at {dest} around {expected_arrival_text}"
            elif not_started and level == "on_time":
                headline = f"Departs at {live['departs_at']}: on time"
            paragraphs.append(f"Good news, {label} {_delay_phrase(minutes)}." if level == "on_time"
                              else f"{label} {_delay_phrase(minutes)}.")
            if expected_arrival_text:
                if level == "on_time":
                    paragraphs.append(f"It's scheduled to reach **{dest}** at **{scheduled_arrival_text}**.")
                else:
                    paragraphs.append(
                        f"Instead of the scheduled **{scheduled_arrival_text}**, you can expect it at **{dest}** "
                        f"around **{expected_arrival_text}**."
                    )
            paragraphs.extend(disruption_lines)
            paragraphs.append(_position_sentence(ctx, live))
            if live and live["baseline_minutes"] and estimate:
                paragraphs.append(f"About **{live['baseline_minutes']} min** of that is this service's typical "
                                  f"running delay. {_confidence_phrase(estimate.get('confidence', ''))}")
            elif estimate and not live:
                paragraphs.append(_confidence_phrase(estimate.get("confidence", "")))
    elif intent == "eta":
        headline = f"Scheduled to arrive at {scheduled_arrival_text}"
        paragraphs.append(f"{label} is scheduled to reach **{dest}** at **{scheduled_arrival_text}**.")
        paragraphs.append(_position_sentence(ctx, live))
    elif intent == "location":
        headline = {"SCHEDULED": "Not departed yet", "ARRIVED": "Journey completed",
                    "AT_STATION": f"At {live['at_station']}" if live else "Where the train is now",
                    }.get(live["status"] if live else "", "Where the train is now")
        if live and live["status"] == "IN_TRANSIT":
            headline = f"Between {live['last_station']} and {live['next_station']}"
        paragraphs.append(_position_sentence(ctx, live))
        if minutes is not None and not arrived:
            paragraphs.append(f"Expected at **{dest}** around **{expected_arrival_text}**"
                              + (f", about **{minutes:.0f} min** late." if level != "on_time" else ", on time."))
        paragraphs.extend(disruption_lines)
        show_timeline = bool(live)
    elif intent == "departure":
        headline = f"Departs at {_clock(departure)}"
        paragraphs.append(
            f"{label} leaves **{ctx.get('from_station') or 'its origin'}** at **{_clock(departure)}** "
            f"and is due into **{dest}** at **{scheduled_arrival_text}**."
        )
        paragraphs.append(_position_sentence(ctx, live))
    elif intent == "reason":
        headline = "What could cause a delay"
        if disruption_lines:
            headline = "Why it's running late"
            paragraphs.extend(disruption_lines)
        elif live_incidents:
            inc = live_incidents[0]
            paragraphs.append(
                f"There's a report today of {_cause(inc.get('classified_type'))} near "
                f"**{inc.get('station') or 'the line'}**, which may slow this service down."
            )
        elif minutes is not None and _delay_level(minutes) == "on_time":
            paragraphs.append("Nothing is expected to hold it up; there are no reported problems on its route today.")
        else:
            paragraphs.append("There are no reported problems on its route today, so any delay would come from "
                              "normal running on this line.")
        if live and live["baseline_minutes"] > 2:
            paragraphs.append(f"This service typically runs about **{live['baseline_minutes']} min** late "
                              "(RailSense delay model).")
        if precedent:
            p = precedent[0]
            paragraphs.append(
                f"In the past, delays on this line have mostly come from {_cause(p.get('incident_type'))}. "
                f"For example, one at **{p.get('station') or 'a nearby station'}** held trains for about "
                f"**{float(p.get('delay_minutes') or 0):.0f} minutes**."
            )
    elif intent == "maintenance":
        headline = "Train condition"
        paragraphs.append(
            f"{label} has no open maintenance issues and is cleared for service."
            if not out_of_service else f"{label} is currently under maintenance."
        )
    elif intent == "incidents":
        on_route = [d for d in (live or {}).get("disruptions", [])]
        if on_route:
            headline = f"{len(on_route)} verified alert{'s' if len(on_route) > 1 else ''} on this train's route"
            paragraphs.extend(_disruption_sentences(live, only_this_run=False))
            if any(not d["affects_this_run"] for d in on_route):
                paragraphs.append("Alerts at points this run had already passed when they were reported don't "
                                  "change its times.")
        elif live_incidents:
            headline = f"{len(live_incidents)} report{'s' if len(live_incidents) > 1 else ''} on this line today"
            for inc in live_incidents[:3]:
                paragraphs.append(
                    f"• {_cause(inc.get('classified_type')).capitalize()} reported near "
                    f"**{inc.get('station') or 'the line'}**: {inc.get('summary') or 'details pending'}"
                )
        else:
            headline = "All clear on this line"
            paragraphs.append("No incidents have been reported on this train's route today.")
    elif intent == "stops":
        headline = f"{ctx.get('from_station') or 'Origin'} → {dest}"
        if live:
            headline = "Station timetable"
            paragraphs.append(f"{label} calls at {len(live['timeline'])} stations. Expected times include "
                              "today's verified delays.")
            if live["path_source"] != "board_stops":
                paragraphs.append("Today's board doesn't list its stops, so these are the standard stations on "
                                  "this line; intermediate times are estimated from distance along the track.")
            else:
                paragraphs.append("Intermediate times are estimated from distance along the track between the "
                                  "published departure and arrival.")
            paragraphs.extend(disruption_lines)
            show_timeline = True
        else:
            stops = ctx.get("stops") or []
            if stops:
                paragraphs.append(f"{label} calls at: " + " → ".join(f"**{s}**" for s in stops) + ".")
            else:
                paragraphs.append(
                    f"{label} runs from **{ctx.get('from_station') or 'its origin'}** to **{dest}**. "
                    "The full list of stops isn't published for today's service."
                )

    if (live_incidents and not live and intent in ("delay", "status", "eta", "location")
            and not out_of_service):
        inc = live_incidents[0]
        paragraphs.append(
            f"Heads up: {_cause(inc.get('classified_type'))} was reported near "
            f"**{inc.get('station') or 'the line'}** today."
        )

    facts: list[dict[str, str]] = []
    if minutes is not None and not arrived and not out_of_service:
        facts.append({"label": "Expected delay", "value": "On time" if level == "on_time" else f"{minutes:.0f} min",
                      "tone": "good" if level in ("on_time", "minor") else "warn" if level == "moderate" else "bad"})
    if expected_arrival_text and not arrived and not out_of_service:
        facts.append({"label": "Expected arrival", "value": expected_arrival_text, "tone": "neutral"})
    if live and live["status"] in ("IN_TRANSIT", "AT_STATION") and live.get("next_station"):
        nxt = next((r for r in live["timeline"] if r["station"] == live["next_station"]), None)
        if nxt:
            facts.append({"label": f"Next: {nxt['station']}", "value": nxt["expected"], "tone": "neutral"})
    elif departure:
        facts.append({"label": "Departure", "value": _clock(departure), "tone": "neutral"})
    if arrived and live:
        facts.append({"label": "Arrived", "value": live["expected_arrival"], "tone": "good"})
    facts.append({"label": "Train condition", "value": "Under maintenance" if out_of_service else "Cleared",
                  "tone": "bad" if out_of_service else "good"})

    gauge = None
    if minutes is not None and not arrived and not out_of_service:
        gauge = {"minutes": round(minutes, 1), "level": level,
                 "confidence": (estimate or {}).get("confidence", "medium")}

    sources = ["Today's live schedule"]
    if live:
        sources.append(f"Live position at {live['now']}")
    if estimate:
        sources.append("This train's recorded journeys" if estimate.get("method") == "historical_record"
                       else "RailSense delay model")
    if live and live.get("disruptions"):
        sources.append("Verified incident map")
        if any(d.get("basis") for d in live["disruptions"]):
            sources.append("Similar past incidents (IR)")
    if precedent:
        sources.append("Past incident records")
    if live_incidents and not live:
        sources.append("Today's incident reports")

    return {
        "intent": intent,
        "headline": headline,
        "paragraphs": paragraphs,
        "facts": facts,
        "gauge": gauge,
        "suggestions": _SUGGESTIONS.get(intent, _SUGGESTIONS["status"]),
        "sources": sources,
        "handoff": False,
        "timeline": _timeline_view(live) if show_timeline and not out_of_service else None,
        "live": ({k: live[k] for k in ("status", "now", "current_station", "last_station", "next_station",
                                        "at_station", "progress_percent", "delay_minutes", "expected_arrival",
                                        "departs_at", "service_day")} if live else None),
    }
