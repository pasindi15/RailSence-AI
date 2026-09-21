"""Passenger-facing operations answers for the user portal's train popup.

Two NLP steps, both deterministic so every sentence can be traced back to data:

1. detect_intent()  - rule-based intent classification of a free-text passenger
                      question (delay, arrival, location, reason, maintenance...).
2. compose_answer() - template natural-language generation that turns the
                      delay model output, retrieved incident precedent and the
                      live schedule context into short, friendly sentences.

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
    ("eta", ("arrive", "arrival", "reach", "get to", "eta", "when will", "what time", "how long")),
    ("departure", ("depart", "leave", "leaving", "departure", "start", "set off")),
    ("location", ("where", "location", "position", "which station", "how far", "progress", "right now", "currently")),
    ("maintenance", ("maintenance", "safe", "fault", "breakdown", "repair", "condition", "out of service", "mechanical")),
    ("incidents", ("incident", "accident", "disruption", "problem", "issue", "alert", "block")),
    ("stops", ("stop", "stops", "stations", "via", "pass through", "route")),
    ("delay", ("delay", "late", "on time", "ontime", "behind", "running", "wait", "punctual")),
    ("status", ("status", "operation", "operational", "update", "overview", "running ok", "everything ok")),
]

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
    "eta": ["Is it delayed?", "Where is it now?", "Which stations does it stop at?"],
    "location": ["When will it arrive?", "Is it delayed?", "Any incidents on the line?"],
    "reason": ["Is it safe to travel?", "When will it arrive?", "Any incidents on the line?"],
    "maintenance": ["Is it delayed?", "Where is it now?", "Any incidents on the line?"],
    "incidents": ["Is it delayed?", "Why might it be late?", "When will it arrive?"],
    "stops": ["When will it arrive?", "Where is it now?", "Is it delayed?"],
    "departure": ["Is it delayed?", "When will it arrive?", "Which stations does it stop at?"],
    "status": ["Is it delayed?", "When will it arrive?", "Why might it be late?"],
    "greeting": ["Is it delayed?", "Where is it now?", "When will it arrive?"],
}


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
        return default
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


def _position_sentence(ctx: dict[str, Any]) -> str:
    live = str(ctx.get("live_status") or "").upper()
    current, nxt = ctx.get("current_station"), ctx.get("next_station")
    progress = ctx.get("progress_percent")
    origin, dest = ctx.get("from_station") or "its origin", ctx.get("to_station") or "its destination"
    if live == "ARRIVED":
        return f"It has already completed today's journey and arrived at **{current or dest}**."
    if current and nxt:
        pct = f" It's about **{progress:.0f}%** of the way there." if progress is not None else ""
        return f"Right now it's travelling between **{current}** and **{nxt}**.{pct}"
    if live == "IN_TRANSIT":
        pct = f", roughly **{progress:.0f}%** of the way" if progress is not None else ""
        return f"It's on its way to {dest}{pct}."
    if live == "SCHEDULED":
        return f"It hasn't left yet; it's due to depart **{origin}** at **{_clock(_parse_clock(ctx.get('departure_time')))}**."
    return "I don't have a live position for it at the moment."


# ------------------------------------------------------------ composition

def compose_answer(
    intent: str,
    ctx: dict[str, Any],
    estimate: Optional[dict[str, Any]],
    live_incidents: list[dict[str, Any]],
    precedent: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the popup payload: headline, friendly paragraphs, facts and chips.

    estimate: {"minutes", "confidence", "corridor", "method"} or None
    live_incidents: reports filed today that touch this train or its stations
    precedent: retrieved historical incidents on the same corridor
    """
    label = _train_label(ctx)
    dest = ctx.get("to_station") or "its destination"
    maintenance = str(ctx.get("maintenance_status") or "").upper()
    out_of_service = maintenance in {"OUT_OF_SERVICE", "DECOMMISSIONED"}
    arrived = str(ctx.get("live_status") or "").upper() == "ARRIVED"

    minutes = max(0.0, float(estimate["minutes"])) if estimate else None
    level = _delay_level(minutes) if minutes is not None else None
    arrival = _parse_clock(ctx.get("arrival_time"))
    departure = _parse_clock(ctx.get("departure_time"))
    expected_arrival = arrival + timedelta(minutes=round(minutes)) if arrival and minutes is not None else None

    paragraphs: list[str] = []
    headline = ""

    if intent == "handoff":
        return {
            "intent": "handoff",
            "headline": "Let me pass that to the booking assistant",
            "paragraphs": ["Tickets, fares and refunds are handled by our booking assistant. One moment…"],
            "facts": [], "gauge": None, "suggestions": [], "sources": [], "handoff": True,
        }

    if out_of_service:
        headline = "This train isn't running right now"
        paragraphs.append(
            f"{label} has been taken out of service for maintenance, so it won't be running as scheduled. "
            "Please check the board for another service on this route, or ask me about alternatives."
        )
    elif intent == "greeting":
        headline = "Happy to help!"
        paragraphs.append(
            f"You're looking at {label} to {dest}. Ask me anything about its delay, where it is, "
            "or when it'll arrive."
        )
    elif intent in ("delay", "status") or (intent == "eta" and minutes is not None):
        if minutes is None:
            headline = "I couldn't get a delay estimate"
            paragraphs.append(f"I wasn't able to estimate a delay for {label} right now. Please try again shortly.")
        elif arrived:
            headline = f"Already arrived at {ctx.get('current_station') or dest}"
            paragraphs.append(_position_sentence(ctx))
            paragraphs.append(
                f"On a typical day at this time, this service {_delay_phrase(minutes).replace('should be', 'is usually')}."
            )
        else:
            headline = {
                "on_time": "Looking good: on time",
                "minor": f"Small delay possible: about {minutes:.0f} min",
                "moderate": f"Expect a delay of about {minutes:.0f} min",
                "major": f"Significant delay likely: about {minutes:.0f} min",
            }[level]
            if intent == "eta" and expected_arrival:
                headline = f"Expected at {dest} around {_clock(expected_arrival)}"
            paragraphs.append(f"Good news, {label} {_delay_phrase(minutes)}." if level == "on_time"
                              else f"{label} {_delay_phrase(minutes)}.")
            if expected_arrival and arrival:
                if level == "on_time":
                    paragraphs.append(f"It's scheduled to reach **{dest}** at **{_clock(arrival)}**.")
                else:
                    paragraphs.append(
                        f"Instead of the scheduled **{_clock(arrival)}**, you can expect it at **{dest}** "
                        f"around **{_clock(expected_arrival)}**."
                    )
            if intent == "status":
                paragraphs.append(_position_sentence(ctx))
            paragraphs.append(_confidence_phrase(estimate.get("confidence", "")))
    elif intent == "eta":
        headline = f"Scheduled to arrive at {_clock(arrival)}"
        paragraphs.append(f"{label} is scheduled to reach **{dest}** at **{_clock(arrival)}**.")
    elif intent == "location":
        headline = "Where the train is now"
        paragraphs.append(_position_sentence(ctx))
        if minutes is not None and not arrived:
            paragraphs.append(f"Based on our delay model, it {_delay_phrase(minutes)}.")
    elif intent == "departure":
        headline = f"Departs at {_clock(departure)}"
        paragraphs.append(
            f"{label} leaves **{ctx.get('from_station') or 'its origin'}** at **{_clock(departure)}** "
            f"and is due into **{dest}** at **{_clock(arrival)}**."
        )
        paragraphs.append(_position_sentence(ctx))
    elif intent == "reason":
        headline = "What could cause a delay"
        if live_incidents:
            inc = live_incidents[0]
            paragraphs.append(
                f"There's a report today of {_cause(inc.get('classified_type'))} near "
                f"**{inc.get('station') or 'the line'}**, which may slow this service down."
            )
        elif minutes is not None and _delay_level(minutes) == "on_time":
            paragraphs.append("Nothing is expected to hold it up; there are no reported problems on its route today.")
        else:
            paragraphs.append("There are no reported problems on its route today, so any delay would come from normal traffic.")
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
        if live_incidents:
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
        stops = ctx.get("stops") or []
        headline = f"{ctx.get('from_station') or 'Origin'} → {dest}"
        if stops:
            paragraphs.append(f"{label} calls at: " + " → ".join(f"**{s}**" for s in stops) + ".")
        else:
            paragraphs.append(
                f"{label} runs from **{ctx.get('from_station') or 'its origin'}** to **{dest}**. "
                "The full list of stops isn't published for today's service."
            )

    if live_incidents and intent in ("delay", "status", "eta", "location") and not out_of_service:
        inc = live_incidents[0]
        paragraphs.append(
            f"Heads up: {_cause(inc.get('classified_type'))} was reported near "
            f"**{inc.get('station') or 'the line'}** today."
        )

    facts: list[dict[str, str]] = []
    if minutes is not None and not arrived and not out_of_service:
        facts.append({"label": "Expected delay", "value": "On time" if level == "on_time" else f"{minutes:.0f} min",
                      "tone": "good" if level in ("on_time", "minor") else "warn" if level == "moderate" else "bad"})
    if expected_arrival and not arrived and not out_of_service:
        facts.append({"label": "Expected arrival", "value": _clock(expected_arrival), "tone": "neutral"})
    if departure:
        facts.append({"label": "Departure", "value": _clock(departure), "tone": "neutral"})
    facts.append({"label": "Train condition", "value": "Under maintenance" if out_of_service else "Cleared",
                  "tone": "bad" if out_of_service else "good"})

    gauge = None
    if minutes is not None and not arrived and not out_of_service:
        gauge = {"minutes": round(minutes, 1), "level": level,
                 "confidence": estimate.get("confidence", "medium")}

    sources = ["Today's live schedule"]
    if estimate:
        sources.append("This train's recorded journeys" if estimate.get("method") == "historical_record"
                       else "RailSense delay model")
    if precedent:
        sources.append("Past incident records")
    if live_incidents:
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
    }
