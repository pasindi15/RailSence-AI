"""Operational status answers for the maintenance assistant: NLP -> IR -> RAG.

Questions like "What trains are unavailable today due to maintenance?" or "Is the
Yal Devi running today? I have a booking on it." are about the live fleet, not about
manuals. This module answers them from M4's own data, deterministically:

1. NLP   detect_ops_intent(): intent (fleet_unavailable / train_status / fleet_risk)
         and named-entity recognition of the train (name with typo tolerance, M4 id
         T-00x, service number, shared-registry id such as 4085, loco or asset id).
2. IR    live evidence: maintenance flags (the same ones the Train Flags panel and
         M3 Booking use), each linked asset's LATEST inspection record, open field
         reports.
3. RAG   manual sections retrieved only for assets that actually show a fault, so
         guidance is relevant (no pantograph advice for a brake question).
4. NLG   a templated answer in the assistant's Status / Assets / Details / Action /
         Reference format. Every number comes from the records; nothing is invented.
"""

from __future__ import annotations

import csv
import difflib
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from rag.manual_retriever import retrieve_manual_sections

AGENT_DIR = Path(__file__).resolve().parents[1]
ASSETS_CSV = AGENT_DIR / "data" / "assets_history.csv"

# M4 fleet (same ids as the dashboard's TRAINS list) + ids other RailSense modules use.
FLEET: list[dict[str, Any]] = [
    {"id": "T-001", "name": "Udarata Menike", "number": "1015", "loco": "DE-1001", "route": "Colombo Fort–Badulla",
     "aliases": ["1015"], "assets": ["DE-1001", "BG-1001", "BR-1001"]},
    {"id": "T-002", "name": "Intercity Express", "number": "1083", "loco": "DE-1002", "route": "Colombo Fort–Kandy",
     "aliases": ["1083", "IC-8746", "IC-1001", "PM-4082"], "assets": ["DE-1002", "BG-1002", "BR-1002"]},
    {"id": "T-003", "name": "Yal Devi", "number": "1001", "loco": "DE-2001", "route": "Colombo Fort–Jaffna",
     "aliases": ["4085"], "assets": ["DE-2001", "BG-1006", "BR-1005"]},
    {"id": "T-004", "name": "Ruhunu Kumari", "number": "1078", "loco": "DE-2002", "route": "Colombo Fort–Matara",
     "aliases": ["1078"], "assets": ["DE-2002", "BG-1007", "BR-1006"]},
    {"id": "T-005", "name": "Podi Menike", "number": "1019", "loco": "DE-1003", "route": "Kandy–Badulla",
     "aliases": ["1019", "1005", "PM-8056"], "assets": ["DE-1003", "BG-1003", "BR-1003"]},
    {"id": "T-006", "name": "Galu Kumari", "number": "1084", "loco": "DE-1004", "route": "Colombo Fort–Galle",
     "aliases": ["1084"], "assets": ["DE-1004", "BG-1004", "BR-1004"]},
    {"id": "T-007", "name": "Night Mail", "number": "1045", "loco": "DE-2003", "route": "Colombo Fort–Matara",
     "aliases": ["1045", "DM-8055"], "assets": ["DE-2003", "BG-1008", "BR-1007"]},
    {"id": "T-008", "name": "Denuwara Menike", "number": "1087", "loco": "DE-2004", "route": "Colombo Fort–Kandy",
     "aliases": ["1087"], "assets": ["DE-2004", "BG-1009", "BR-1008"]},
]
ASSET_LABEL = {"diesel_engine": "Diesel Engine", "bogie": "Bogie", "brake_system": "Brake System"}
MANUAL_FOR = {"diesel_engine": "diesel_engine_manual", "bogie": "bogie_inspection_guide",
              "brake_system": "brake_system_manual"}

# ------------------------------------------------------------------ 1. NLP
_UNAVAILABLE = re.compile(
    r"\b(unavailable|not available|out of service|not running|won'?t run|cancel\w*|suspend\w*|grounded|withdrawn|"
    r"off (?:the )?(?:road|service)|under maintenance|in maintenance|for maintenance|flagged|taken off|"
    r"can'?t run|not operating|disrupt\w*)\b", re.I)
_STATUS = re.compile(
    r"\b(running|run|runs|operating|operate|in service|available|status|cancel\w*|booking|booked|ticket|"
    r"safe|on time|delay\w*|today|tomorrow|tonight|go ahead|depart\w*|cleared|fit)\b", re.I)
_RISK = re.compile(
    r"\b(at risk|critical|red|failing|worst|attention|urgent|highest risk|fleet health|health of the fleet|"
    r"needs? (?:inspection|service)|overdue)\b", re.I)
_FLEET_WORD = re.compile(r"\b(trains?|fleet|services?|locos?|locomotives?|assets?)\b", re.I)
_TRAIN_ID = re.compile(r"\b(T-\d{3}|[A-Z]{2}-\d{4}|\d{2,5})\b", re.I)


def find_train(message: str) -> Optional[dict]:
    """Named-entity recognition for trains: exact name, ids/aliases/assets, then fuzzy name."""
    low = message.lower()
    for t in FLEET:
        if t["name"].lower() in low:
            return t
    tokens = {m.upper() for m in _TRAIN_ID.findall(message)}
    for t in FLEET:
        keys = {t["id"], t["number"], t["loco"], *t["aliases"], *t["assets"]}
        if tokens & {k.upper() for k in keys}:
            return t
    words = re.sub(r"[^a-z\s]", " ", low).split()
    grams = {" ".join(words[i:i + n]) for n in (2, 3) for i in range(len(words) - n + 1)}
    best, score = None, 0.0
    for g in grams:
        for t in FLEET:
            s = difflib.SequenceMatcher(None, g, t["name"].lower()).ratio()
            if s > score:
                best, score = t, s
    return best if score >= 0.82 else None


def detect_ops_intent(message: str) -> tuple[Optional[str], Optional[dict]]:
    train = find_train(message)
    unavailable, status, risk = (bool(r.search(message)) for r in (_UNAVAILABLE, _STATUS, _RISK))
    if train and (status or unavailable):
        return "train_status", train
    if not train and unavailable and _FLEET_WORD.search(message):
        return "fleet_unavailable", None
    if not train and risk and _FLEET_WORD.search(message):
        return "fleet_risk", None
    return None, train


# ------------------------------------------------------------------ 2. IR
_CACHE: dict[str, Any] = {"at": 0.0, "rows": {}, "source": ""}


def latest_records() -> tuple[dict[str, dict], str]:
    """asset_id -> its most recent inspection record (Supabase if configured, else the CSV)."""
    if time.monotonic() - _CACHE["at"] < 60 and _CACHE["rows"]:
        return _CACHE["rows"], _CACHE["source"]
    rows: list[dict] = []
    source = "assets_history.csv"
    try:
        import supabase_store
        client = supabase_store.get_client()
        if client is not None:
            ids = [a for t in FLEET for a in t["assets"]]
            rows = (client.table("assets_history").select("*").in_("asset_id", ids)
                    .order("last_service_date", desc=True).limit(500).execute().data or [])
            source = "Supabase assets_history"
    except Exception:
        rows = []
    if not rows and ASSETS_CSV.exists():
        with ASSETS_CSV.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        source = "assets_history.csv"
    latest: dict[str, dict] = {}
    for r in rows:
        aid = r.get("asset_id")
        if aid and (aid not in latest or str(r.get("last_service_date", "")) > str(latest[aid].get("last_service_date", ""))):
            latest[aid] = r
    _CACHE.update(at=time.monotonic(), rows=latest, source=source)
    return latest, source


def _flag_for(train: dict, flags: dict[str, dict]) -> Optional[dict]:
    keys = {k.upper() for k in (train["id"], train["number"], train["loco"], *train["aliases"])}
    for fid, f in flags.items():
        if str(fid).upper() in keys:
            return f
    return None


def _open_reports(train: dict, reports: list[dict]) -> list[dict]:
    names = {train["name"].lower(), train["id"].lower()}
    out = []
    for r in reports:
        if r.get("resolved_at"):
            continue
        blob = " ".join(str(r.get(k, "")) for k in ("asset_id", "train_id", "summary")).lower()
        if r.get("asset_id") in train["assets"] or any(n in blob for n in names):
            out.append(r)
    return out


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def train_snapshot(train: dict, flags: dict, reports: list[dict]) -> dict:
    latest, source = latest_records()
    assets = [latest[a] for a in train["assets"] if a in latest]
    flag = _flag_for(train, flags)
    statuses = [str(a.get("health_status", "")).upper() for a in assets]
    state = ("OUT_OF_SERVICE" if flag else "AT_RISK" if "RED" in statuses
             else "WATCH" if "AMBER" in statuses else "OK" if assets else "NO_DATA")
    dates = [str(a.get("last_service_date", "")) for a in assets if a.get("last_service_date")]
    return {"train": train, "flag": flag, "assets": assets, "state": state, "source": source,
            "as_of": max(dates) if dates else None, "reports": _open_reports(train, reports)}


# ------------------------------------------------------------------ 3. RAG
MIN_RELEVANCE = 0.10  # TF-IDF cosine below this is noise for these queries (measured: status questions score ~0.07)
_STOP = {"and", "the", "of", "for", "a", "an", "to", "in", "on", "inspection", "maintenance", "system", "action"}


def _retrieve(query: str, asset_type: str = "", manual_file: Optional[str] = None, top_k: int = 5,
              boost: str = "") -> list[dict]:
    """IR over the manuals: retrieve, keep relevant hits, re-rank by overlap of `boost` words with the title."""
    try:
        sections, method = retrieve_manual_sections(query=query, asset_type=asset_type, top_k=top_k)
    except Exception:
        return []
    terms = {w for w in re.findall(r"[a-z]+", (boost or query).lower()) if w not in _STOP and len(w) > 2}
    out = []
    for sec in sections:
        if manual_file and manual_file not in sec.get("source_file", ""):
            continue
        score = float(sec.get("score") or 0)
        if score < MIN_RELEVANCE:
            continue
        title_terms = set(re.findall(r"[a-z]+", str(sec.get("section_title", "")).lower()))
        out.append({**sec, "retrieval_method": method, "_rank": score + 0.15 * len(terms & title_terms)})
    return sorted(out, key=lambda x: x["_rank"], reverse=True)


def manual_guidance(asset: dict) -> Optional[dict]:
    """RAG for one faulty asset: query rewritten from the record (fault + asset type)."""
    atype = str(asset.get("asset_type", ""))
    fault = str(asset.get("fault_type") or "").replace("_", " ")
    # The manual is already fixed by asset type, so the query carries only the fault words;
    # the generic asset name ("Bogie") would otherwise pull every section towards the overview.
    hits = _retrieve(f"{fault} limits corrective action", atype, MANUAL_FOR.get(atype), boost=fault)
    return hits[0] if hits else None


# Query rewriting: status questions are not in the manuals, the POLICY behind them is.
# Phrased the way the SLR manuals state fitness-to-run limits (measured against the corpus).
_FITNESS = ["brake cylinder leak overhauled immediately do not attempt to continue the journey",
            "engine temperature exceeding 100 degrees overheating shut down locomotive",
            "bearing temperature above 70 degrees vibration level bogie limit"]
_POLICY_QUERIES = {
    "fleet_unavailable": _FITNESS,
    "fleet_risk": _FITNESS[::-1],
    "train_status": _FITNESS,
}


def policy_sections(intent: str, limit: int = 2) -> list[dict]:
    seen, out = set(), []
    for q in _POLICY_QUERIES.get(intent, []):
        for sec in _retrieve(q):
            key = (sec.get("source_file"), sec.get("section_title"))
            if key not in seen:
                seen.add(key)
                out.append(sec)
    return sorted(out, key=lambda x: x["_rank"], reverse=True)[:limit]


# ------------------------------------------------------------------ 4. NLG
def _asset_line(a: dict) -> str:
    return (f"- {a.get('asset_id')} | {ASSET_LABEL.get(a.get('asset_type'), a.get('asset_type'))} | "
            f"{_num(a.get('health_score')):.1f} | {str(a.get('health_status', '')).upper()}")


def _age(d: Optional[str]) -> str:
    try:
        days = (date.today() - date.fromisoformat(str(d)[:10])).days
        return f"{d} ({days} day{'s' if days != 1 else ''} ago)"
    except (TypeError, ValueError):
        return str(d or "unknown")


def _first_sentence(text: str, limit: int = 220) -> str:
    t = " ".join(str(text or "").split())
    cut = re.split(r"(?<=[.!?])\s", t, maxsplit=1)[0]
    return (cut[:limit] + "…") if len(cut) > limit else cut


def _data_citations(snaps: list[dict], used_flags: bool) -> list[dict]:
    cites = []
    if used_flags:
        cites.append({"manual": "Live maintenance flags", "section_title": "Train Flags panel (shared with M3 Booking)",
                      "snippet": "Trains flagged out of service by engineers; M3 Booking stops new bookings for them.",
                      "source_file": "train_flags.jsonl", "score": None})
    as_of = max((s["as_of"] for s in snaps if s["as_of"]), default=None)
    if snaps:
        cites.append({"manual": "Latest inspection records", "section_title": f"Asset health (as of {as_of or 'n/a'})",
                      "snippet": "Most recent inspection per linked asset: health score, status, faults, recommended action.",
                      "source_file": snaps[0]["source"], "score": None})
    return cites


def _manual_citation(g: dict) -> dict:
    return {"manual": g.get("manual"), "section_title": g.get("section_title"),
            "snippet": str(g.get("content", ""))[:300], "source_file": g.get("source_file"), "score": g.get("score")}


def answer_train_status(message: str, train: dict, flags: dict, reports: list[dict]) -> dict:
    snap = train_snapshot(train, flags, reports)
    t, flag, assets = train, snap["flag"], snap["assets"]
    label = f"{t['name']} (Train {t['id']} · #{t['number']} · Loco {t['loco']})"
    booking = bool(re.search(r"\b(booking|booked|ticket|reservation)\b", message, re.I))
    details, actions, cites, guidance = [], [], [], []

    if flag:
        status = f"No — {label} is currently OUT OF SERVICE for maintenance."
        details.append(f"Flag reason: {flag.get('reason') or 'not stated'} (severity {flag.get('severity') or 'n/a'}, "
                       f"flagged by {flag.get('flagged_by') or 'engineer'} at {str(flag.get('flagged_at', ''))[:16].replace('T', ' ')} UTC).")
        if flag.get("estimated_clear"):
            details.append(f"Expected back in service: {flag['estimated_clear']}.")
        if flag.get("delay_minutes") is not None:
            details.append(f"Expected service delay: {flag['delay_minutes']} minutes.")
        if booking:
            details.append("New bookings on this train are blocked while the flag is active; existing bookings should be "
                           "moved to another service or cancelled through the booking desk.")
        actions.append("Complete the repair, then clear the flag in the Train Flags panel to return the train to service.")
    elif snap["state"] == "AT_RISK":
        status = (f"Yes — {label} is not flagged, so it is scheduled to run, but at least one linked asset is RED "
                  "and needs attention before its next departure.")
    elif snap["state"] == "WATCH":
        status = f"Yes — {label} is not flagged for maintenance and is cleared to run; some assets are AMBER (monitor)."
    elif snap["state"] == "OK":
        status = f"Yes — {label} is not flagged for maintenance and all linked assets are GREEN, so it is cleared to run."
    else:
        status = f"{label} has no maintenance flag, but M4 has no inspection records for its assets."

    if not flag and booking:
        details.append("Bookings on this train are unaffected: M3 Booking only stops sales when M4 flags a train out of service.")
    for a in assets:
        st = str(a.get("health_status", "")).upper()
        fault = a.get("fault_type") or "none"
        if st in ("RED", "AMBER"):
            details.append(f"{a.get('asset_id')} ({ASSET_LABEL.get(a.get('asset_type'), a.get('asset_type'))}) is {st} "
                           f"at {_num(a.get('health_score')):.1f}/100 — fault: {fault}, {a.get('fault_count_30d', 0)} fault(s) "
                           f"in 30 days, last serviced {_age(a.get('last_service_date'))}.")
            if a.get("recommended_action"):
                actions.append(f"{a.get('asset_id')}: {a['recommended_action']}")
            g = manual_guidance(a)
            if g:
                guidance.append(g)
                details.append(f"Manual guidance for {a.get('asset_id')}: {g.get('section_title')} — "
                               f"{_first_sentence(g.get('content'))}")
    if not any(str(a.get("health_status", "")).upper() in ("RED", "AMBER") for a in assets) and assets:
        if flag:
            details.append(f"Its latest inspections (as of {snap['as_of']}) were all GREEN — the flagged fault was "
                           "reported after them, so the flag takes precedence.")
        else:
            details.append(f"All {len(assets)} linked assets are GREEN (latest inspections as of {snap['as_of']}).")
    for r in snap["reports"][:3]:
        details.append(f"Open field report {r.get('ticket_id') or r.get('report_id')}: {_first_sentence(r.get('summary'), 140)}")
    if not actions:
        actions.append("None at this time — continue scheduled maintenance.")

    parts = [f"**Status:** {status}"]
    if assets:
        parts.append("**Assets:**\n" + "\n".join(_asset_line(a) for a in assets))
    parts.append("**Details:**\n" + "\n".join(f"- {d}" for d in details))
    parts.append("**Action Required:**\n" + "\n".join(f"- {a}" for a in actions))
    ref = ["live maintenance flags", f"latest inspection records ({snap['source']}, as of {snap['as_of'] or 'n/a'})"]
    ref += [f"{g.get('manual')} — {g.get('section_title')}" for g in guidance]
    parts.append("**Reference:** " + "; ".join(ref) + ".")
    if not guidance:
        guidance = policy_sections("train_status", 1)
    cites = _data_citations([snap], True) + [_manual_citation(g) for g in guidance]
    level = {"OUT_OF_SERVICE": "RED", "AT_RISK": "RED", "WATCH": "AMBER", "OK": "GREEN"}.get(snap["state"], "INFO")
    return _result(message, "\n\n".join(parts), cites, guidance, "train_status", train, level, [snap])


def answer_fleet(message: str, intent: str, flags: dict, reports: list[dict]) -> dict:
    snaps = [train_snapshot(t, flags, reports) for t in FLEET]
    out = [s for s in snaps if s["flag"]]
    risk = [s for s in snaps if not s["flag"] and s["state"] == "AT_RISK"]
    watch = [s for s in snaps if not s["flag"] and s["state"] == "WATCH"]
    unknown_flags = [fid for fid in flags if not any(_flag_for(t, {fid: flags[fid]}) for t in FLEET)]
    details, actions, guidance = [], [], []

    if intent == "fleet_unavailable":
        if out:
            status = f"{len(out)} train(s) are out of service for maintenance: " + ", ".join(s["train"]["name"] for s in out) + "."
        else:
            status = "No trains are out of service for maintenance right now — none of the fleet is flagged."
        for s in out:
            f = s["flag"]
            eta = f", back ~{f['estimated_clear']}" if f.get("estimated_clear") else ""
            details.append(f"{s['train']['name']} ({s['train']['id']}): {f.get('reason') or 'maintenance'} — severity "
                           f"{f.get('severity') or 'n/a'}{eta}.")
        for fid in unknown_flags:
            details.append(f"Flag on {fid} ({flags[fid].get('reason') or 'maintenance'}) — not one of the 8 tracked M4 trains.")
    else:
        status = (f"{len(risk)} train(s) have a RED asset and {len(watch)} have AMBER assets"
                  + (f"; {len(out)} are already out of service." if out else "."))

    if risk:
        details.append("Not flagged (still scheduled to run) but with a RED asset:")
        for s in risk:
            for a in s["assets"]:
                if str(a.get("health_status", "")).upper() == "RED":
                    details.append(f"{s['train']['name']} ({s['train']['id']}): {a.get('asset_id')} "
                                   f"{ASSET_LABEL.get(a.get('asset_type'), a.get('asset_type'))} "
                                   f"{_num(a.get('health_score')):.1f}/100 — fault {a.get('fault_type') or 'none'}, "
                                   f"inspected {a.get('last_service_date')}.")
                    if a.get("recommended_action"):
                        actions.append(f"{a.get('asset_id')} ({s['train']['name']}): {a['recommended_action']}")
                    if len(guidance) < 2:
                        g = manual_guidance(a)
                        if g:
                            guidance.append(g)
    if watch and intent == "fleet_risk":
        details.append("AMBER (monitor): " + ", ".join(s["train"]["name"] for s in watch) + ".")
    if risk:
        actions.append("If a RED asset must be withdrawn, flag the train in the Train Flags panel — "
                       "that also stops new bookings in M3 automatically.")
    if not actions:
        actions.append("None at this time — continue scheduled maintenance.")
    for g in guidance:
        details.append(f"Manual guidance: {g.get('manual')} — {g.get('section_title')}: {_first_sentence(g.get('content'))}")
    policy = [p for p in policy_sections(intent) if p.get("section_title") not in {g.get("section_title") for g in guidance}]
    for g in policy[:1]:
        details.append(f"Withdrawal policy ({g.get('manual')} — {g.get('section_title')}): {_first_sentence(g.get('content'))}")
    guidance = guidance + policy[:1]

    as_of = max((s["as_of"] for s in snaps if s["as_of"]), default="n/a")
    parts = [f"**Status:** {status}",
             "**Details:**\n" + ("\n".join(f"- {d}" for d in details) if details else
                                 "- All 8 tracked trains are in service; no RED assets in the latest inspections."),
             "**Action Required:**\n" + "\n".join(f"- {a}" for a in actions),
             "**Reference:** live maintenance flags; latest inspection records "
             f"({snaps[0]['source']}, as of {as_of})"
             + ("; " + "; ".join(f"{g.get('manual')} — {g.get('section_title')}" for g in guidance) if guidance else "")
             + "."]
    cites = _data_citations(snaps, True) + [_manual_citation(g) for g in guidance]
    level = "RED" if out or risk else "AMBER" if (watch and intent == "fleet_risk") else "GREEN"
    return _result(message, "\n\n".join(parts), cites, guidance, intent, None, level, snaps)


LLM_SYSTEM = """You are the RailSense AI maintenance assistant for Sri Lanka Railways engineers.
Answer the engineer's question using ONLY the VERIFIED FACTS and MANUAL SECTIONS given.
- Never add a train, asset ID, number, date or fault that is not in the facts or manual text.
- If the facts say nothing is flagged / no RED assets, say so plainly.
- Use manual sections only where they help (e.g. what the fault means or the withdrawal criteria) and name the section.
Reply in EXACTLY this structure:
**Status:** one sentence that directly answers the question.
**Assets:** copy the asset lines from the facts unchanged (omit this section if the facts have none).
**Details:**
- short bullets with the key facts
**Action Required:**
- concrete steps (or "None at this time")
**Reference:** the data sources and manual sections you used."""

_NUM = re.compile(r"\d+(?:\.\d+)?")
_IDS = re.compile(r"\b(?:DE|BG|BR|MT)-[A-Z0-9]{3,6}\b|\bT-\d{3}\b", re.I)


def _grounded(text: str, evidence: str) -> bool:
    """Every number and every train/asset/ticket id in the LLM answer must appear in the evidence."""
    allowed_nums = set(_NUM.findall(evidence))
    for n in _NUM.findall(text):
        if n not in allowed_nums and n.rstrip("0").rstrip(".") not in allowed_nums and f"{float(n):.1f}" not in allowed_nums:
            return False
    allowed_ids = {i.upper() for i in _IDS.findall(evidence)}
    return all(i.upper() in allowed_ids for i in _IDS.findall(text))


def _llm_compose(message: str, facts: str, guidance: list[dict]) -> Optional[str]:
    import os
    if not os.getenv("GROQ_API_KEY"):
        return None
    manual = "\n\n".join(f"[{g.get('manual')} — {g.get('section_title')}]\n{str(g.get('content', ''))[:1200]}"
                          for g in guidance) or "(no manual section passed the relevance threshold)"
    evidence = f"VERIFIED FACTS (live flags + latest inspection records):\n{facts}\n\nMANUAL SECTIONS (retrieved):\n{manual}"
    try:
        from groq import Groq
        resp = Groq(api_key=os.environ["GROQ_API_KEY"]).chat.completions.create(
            model=os.getenv("M4_LLM_MODEL", "qwen/qwen3.8-27b"), max_tokens=700, temperature=0.2,
            messages=[{"role": "system", "content": LLM_SYSTEM},
                      {"role": "user", "content": f"{evidence}\n\nEngineer's question: {message}"}])
        text = (resp.choices[0].message.content or "").strip()
    except Exception:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    # drop sections the model left empty (e.g. "**Assets:**" with no asset lines)
    text = re.sub(r"\*\*[A-Za-z ]+:\*\*\s*(?=\n\*\*|\Z)", "", text).strip()
    if "**Status:**" not in text or not _grounded(text, evidence + " " + message):
        return None
    return text


def _result(message: str, answer: str, citations: list[dict], guidance: list[dict], intent: str,
            train: Optional[dict], level: str, snaps: list[dict]) -> dict:
    """Compose with the LLM from the IR facts + RAG sections; fall back to the grounded template."""
    llm = _llm_compose(message, answer, guidance)
    return {
        "answer": llm or answer,
        "citations": citations,
        "retrieval_method": "live_ir_rag",
        "answer_method": "llm_grounded" if llm else "template_grounded",
        "status_level": level,
        "pipeline": {"nlp": {"intent": intent, "train": train["id"] if train else None},
                     "ir": {"flags": sum(1 for sn in snaps if sn["flag"]), "trains_checked": len(snaps),
                            "records_source": snaps[0]["source"] if snaps else None},
                     "rag": [f"{g.get('manual')} — {g.get('section_title')}" for g in guidance],
                     "llm": bool(llm)},
        "ops_intent": intent,
        "detected_asset_type": "",
        "detected_train": ({"name": train["name"], "loco": train["loco"], "number": train["number"],
                            "route": train["route"], "id": train["id"]} if train else None),
    }


def answer_ops_question(message: str, flags: dict, reports: list[dict]) -> Optional[dict]:
    """Return a grounded operational answer, or None when the question is technical (use manual RAG)."""
    intent, train = detect_ops_intent(message)
    if intent == "train_status":
        return answer_train_status(message, train, flags, reports)
    if intent in ("fleet_unavailable", "fleet_risk"):
        return answer_fleet(message, intent, flags, reports)
    return None
