"""RAG-powered chatbot for maintenance engineers.

Takes a free-text question, retrieves relevant manual sections,
and composes a grounded answer with citations.
"""

import os
import sys
from pathlib import Path
from typing import Any, Optional

from rag.manual_retriever import retrieve_manual_sections, format_citation

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

# ── Train name → locomotive ID mapping ───────────────────────────────────────
TRAIN_NAME_MAP: dict[str, dict] = {
    "udarata menike":    {"loco": "DE-1001", "number": "1015", "route": "Colombo Fort–Badulla"},
    "intercity express": {"loco": "DE-1002", "number": "1083", "route": "Colombo Fort–Kandy"},
    "yal devi":          {"loco": "DE-2001", "number": "1001", "route": "Colombo Fort–Jaffna"},
    "ruhunu kumari":     {"loco": "DE-2002", "number": "1078", "route": "Colombo Fort–Matara"},
    "podi menike":       {"loco": "DE-1003", "number": "1019", "route": "Kandy–Badulla"},
    "galu kumari":       {"loco": "DE-1004", "number": "1084", "route": "Colombo Fort–Galle"},
    "night mail":        {"loco": "DE-2003", "number": "1045", "route": "Colombo Fort–Matara"},
    "denuwara menike":   {"loco": "DE-2004", "number": "1087", "route": "Colombo Fort–Kandy"},
}

# ── Linked rolling-stock assets per train (loco + bogie + brake system) ───────
# Each loco's numeric suffix maps to its paired bogie and brake system unit.
TRAIN_ASSET_MAP: dict[str, list[str]] = {
    "DE-1001": ["DE-1001", "BG-1001", "BR-1001"],
    "DE-1002": ["DE-1002", "BG-1002", "BR-1002"],
    "DE-1003": ["DE-1003", "BG-1003", "BR-1003"],
    "DE-1004": ["DE-1004", "BG-1004", "BR-1004"],
    "DE-2001": ["DE-2001", "BG-1006", "BR-1005"],
    "DE-2002": ["DE-2002", "BG-1007", "BR-1006"],
    "DE-2003": ["DE-2003", "BG-1008", "BR-1007"],
    "DE-2004": ["DE-2004", "BG-1009", "BR-1008"],
}

# ── Reverse map: any rolling-stock asset ID → its loco ID ────────────────────
ASSET_TO_LOCO: dict[str, str] = {
    asset_id: loco_id
    for loco_id, assets in TRAIN_ASSET_MAP.items()
    for asset_id in assets
}

# ── Train-list query detection ────────────────────────────────────────────────
_TRAIN_LIST_KEYWORDS = [
    "train list", "list of trains", "list trains", "all trains", "show trains",
    "what trains", "which trains", "available trains", "trains available",
    "train names", "fleet list", "train fleet",
]

def _is_train_list_query(message: str) -> bool:
    lower = message.lower()
    return any(kw in lower for kw in _TRAIN_LIST_KEYWORDS)

ASSET_TYPE_HINTS: dict[str, list[str]] = {
    "diesel_engine": ["engine", "diesel", "oil", "coolant", "radiator", "crankshaft", "fuel pump", "starter", "overheating", "rpm", "exhaust"],
    "electric_loco": ["pantograph", "inverter", "igbt", "traction motor", "electric", "loco", "overhead"],
    "bogie":         ["bogie", "wheel", "axle", "bearing", "suspension", "spring", "flat spot", "vibration", "profile"],
    "brake_system":  ["brake", "brakes", "pad", "disc", "cylinder", "stopping", "air brake", "vacuum", "glazed", "fade"],
    "signal_unit":   ["signal", "relay", "lamp", "aspect", "point motor", "interlocking", "crossing", "response time"],
    "track_section": ["track", "rail", "sleeper", "ballast", "tamping", "gauge", "geometry", "joint", "crack", "fishplate"],
    "level_crossing":["crossing", "barrier", "gate", "proximity sensor", "level crossing"],
    "platform_gate": ["platform gate", "door", "gate motor"],
}

CASUAL_SYSTEM_PROMPT = """You are a friendly railway maintenance assistant for Sri Lanka Railways (SLR).
For greetings and casual messages respond naturally in 1-2 short sentences.
Briefly introduce yourself and invite the engineer to ask a technical maintenance question.
Never use structured formats like Status/Details/Action for casual conversation."""

_CASUAL_WORDS = {
    "hey", "hi", "hello", "howdy", "sup", "yo",
    "thanks", "thank you", "cheers", "ty",
    "bye", "goodbye", "cya", "ok", "okay", "alright", "sure",
    "good morning", "good afternoon", "good evening", "good night",
    "what can you do", "help", "who are you", "what are you",
}

def _is_casual_message(message: str) -> bool:
    lower = message.strip().lower().rstrip(" !.?,")
    if lower in _CASUAL_WORDS:
        return True
    words = lower.split()
    if len(words) <= 3:
        tech = {"engine","brake","bogie","track","signal","fault","maintenance",
                "service","inspection","repair","oil","fuel","wheel","pad","cylinder",
                "loco","train","asset","health","status","report","check"}
        return not any(w in tech for w in words)
    return False


SYSTEM_PROMPT = """You are an expert railway maintenance engineer assistant for Sri Lanka Railways (SLR).

When the context starts with [FIELD REPORT CONTEXT], use that data to answer questions about specific tickets or reports. Summarise the report details clearly under the standard sections.

Always reply using EXACTLY this structure (use the bold labels as shown):

**Status:** One sentence — current condition or direct answer to the question.

**Assets:** (ONLY when the context contains specific fleet/asset health records — omit this section entirely otherwise)
- ASSET_ID | Asset Type | health_score | HEALTH_STATUS
Example format (one line per asset, pipe-separated, no extra text):
- DE-1003 | Diesel Engine | 91.93 | GREEN
- BG-1003 | Bogie | 66.52 | AMBER
- BR-1003 | Brake System | 75.66 | GREEN

**Details:**
- Key finding or fact 1
- Key finding or fact 2
- Key finding or fact 3 (add more if needed)

**Action Required:**
- Step 1 (most urgent first)
- Step 2
- Step 3

**Action:** (ONLY when the engineer explicitly asks to create, submit, file, or add a report for a specific asset — omit entirely otherwise)
create_report | ASSET_ID | asset_type_snake_case | Station
Example: create_report | BG-1003 | bogie | Kandy
Rules for this section: use the exact asset_id from context; asset_type must be one of: diesel_engine, bogie, brake_system; station is the last known service station from the data.

**Reference:** Manual section, threshold, or interval that applies.

Rules:
- When fleet/asset data is provided, ALWAYS output the **Assets:** section with one pipe-separated line per asset. Use the exact format: ASSET_ID | Asset Type | score | STATUS.
- In **Details:**, describe findings (fault types, days since service, recommendations) — do NOT repeat the asset table here.
- When the engineer asks to CREATE/SUBMIT/FILE/ADD a report for an asset, output the **Action:** section with the create_report line. ALSO provide a brief **Status:** confirming you are opening the report form.
- When manual context is provided but does NOT match the question topic, IGNORE it and answer from expert knowledge. Label the Reference as "General guidance — SLR standard practice".
- When manual context IS relevant, cite it in the Reference line.
- Use only bullet points for lists — no tables, no numbered lists, no markdown headings.
- Be concise. Each bullet should be one clear sentence.
- If a question is outside railway maintenance, say so in the Status line and stop.
- Never leave a section blank — write "None at this time" if nothing applies.
- For greetings or messages with no technical content (e.g. "hey", "hello", "thanks"), reply in plain conversational text — 1-2 sentences only, no structured format at all."""


def _detect_asset_type(message: str) -> str:
    lower = message.lower()
    scores: dict[str, int] = {}
    for asset_type, keywords in ASSET_TYPE_HINTS.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score:
            scores[asset_type] = score
    return max(scores, key=lambda k: scores[k]) if scores else ""


def _detect_train(message: str) -> Optional[dict]:
    """Return train info if the message mentions a known SLR train name, loco ID, train number, or any rolling-stock asset ID."""
    lower = message.lower()
    # 1. Match by train name
    for name, info in TRAIN_NAME_MAP.items():
        if name in lower:
            return {"name": name.title(), **info}
    # 2. Match by loco ID or train number
    for name, info in TRAIN_NAME_MAP.items():
        if info["loco"].lower() in lower or info["number"] in lower:
            return {"name": name.title(), **info}
    # 3. Match by any rolling-stock asset ID (BG-xxxx, BR-xxxx, DE-xxxx)
    import re as _re
    for asset_id in _re.findall(r'\b(?:DE|BG|BR)-\d{4}\b', message, _re.IGNORECASE):
        loco_id = ASSET_TO_LOCO.get(asset_id.upper())
        if loco_id:
            for name, info in TRAIN_NAME_MAP.items():
                if info["loco"] == loco_id:
                    return {"name": name.title(), **info}
    return None


def _fetch_asset_data(loco_id: str) -> Optional[dict]:
    """Fetch the latest health records for a train's full rolling-stock set."""
    asset_ids = TRAIN_ASSET_MAP.get(loco_id, [loco_id])
    try:
        import supabase_store
        client = supabase_store.get_client()
        rows: list[dict] = []
        if client:
            result = (
                client.table("assets_history")
                .select("*")
                .in_("asset_id", asset_ids)
                .order("last_service_date", desc=True)
                .limit(20)
                .execute()
            )
            raw = result.data or []
            # Keep only the latest record per asset_id
            seen: set[str] = set()
            for r in raw:
                aid = r.get("asset_id", "")
                if aid not in seen:
                    seen.add(aid)
                    rows.append(r)
        else:
            import csv
            data_path = AGENT_DIR / "data" / "assets_history.csv"
            if data_path.exists():
                seen2: set[str] = set()
                with open(data_path, encoding="utf-8") as f:
                    for r in csv.DictReader(f):
                        if r.get("asset_id") in asset_ids and r.get("asset_id") not in seen2:
                            seen2.add(r["asset_id"])
                            rows.append(r)
        if not rows:
            return None
        summary = [
            {
                "asset_id": r.get("asset_id"),
                "asset_type": r.get("asset_type", "").replace("_", " "),
                "health_score": r.get("health_score"),
                "health_status": r.get("health_status"),
                "days_since_service": r.get("days_since_service"),
                "fault_type": r.get("fault_type"),
                "fault_count_30d": r.get("fault_count_30d"),
                "recommended_action": r.get("recommended_action"),
                "technician_note": r.get("technician_note"),
                "station": r.get("station"),
                "last_service_date": r.get("last_service_date"),
            }
            for r in rows
        ]
        return {"loco_id": loco_id, "records": summary}
    except Exception:
        return None


def _build_train_list_answer() -> str:
    """Return a formatted train list answer from the known registry."""
    lines = ["**Status:** Here is the current Sri Lanka Railways maintenance fleet registered in RailSense AI.\n"]
    lines.append("**Details:**")
    for name, info in TRAIN_NAME_MAP.items():
        lines.append(f"- {name.title()} — Train #{info['number']} | Loco: {info['loco']} | Route: {info['route']}")
    lines.append("\n**Action Required:**")
    lines.append("- Use a specific train name (e.g. 'Podi Menike engine status') to get live health data.")
    lines.append("- Flag a train for maintenance via the dashboard Train Flags panel.")
    lines.append("- Contact Train Control Center (TCC) for real-time operational schedules.")
    lines.append("\n**Reference:** RailSense M4 internal train registry — 8 tracked locomotives.")
    return "\n".join(lines)


def _build_asset_context(train: dict, asset_data: Optional[dict]) -> str:
    lines = [f"FLEET DATA — {train['name']} (Loco: {train['loco']}, Train #{train['number']}, Route: {train['route']})"]
    if not asset_data or not asset_data.get("records"):
        lines.append("No asset records found in the system for this locomotive.")
        return "\n".join(lines)
    for r in asset_data["records"]:
        status = r.get("health_status", "UNKNOWN")
        score = r.get("health_score", "—")
        fault = r.get("fault_type") or "none"
        note = r.get("technician_note") or "—"
        rec = r.get("recommended_action") or "—"
        lines.append(
            f"  • {r.get('asset_type','?').upper()} | Status: {status} | Health: {score}/100 | "
            f"Faults (30d): {r.get('fault_count_30d','—')} | Fault type: {fault}\n"
            f"    Last service: {r.get('last_service_date','—')} ({r.get('days_since_service','—')} days ago) | Station: {r.get('station','—')}\n"
            f"    Note: {note}\n"
            f"    Recommendation: {rec}"
        )
    return "\n".join(lines)


def _build_manual_context(sections: list[dict]) -> str:
    parts = []
    for i, s in enumerate(sections, 1):
        parts.append(
            f"[Manual {i}] {s.get('manual', '')} — {s.get('section_title', '')}\n"
            f"{s.get('content', '')}"
        )
    return "\n\n".join(parts)


def _template_answer(message: str, sections: list[dict], train: Optional[dict] = None, asset_data: Optional[dict] = None) -> str:
    parts = []
    if train and asset_data and asset_data.get("records"):
        parts.append(f"Fleet data for {train['name']} (Loco {train['loco']}):\n")
        for r in asset_data["records"]:
            parts.append(
                f"• {r.get('asset_type','').replace('_',' ').upper()}: "
                f"{r.get('health_status','?')} (score {r.get('health_score','?')}/100), "
                f"faults last 30d: {r.get('fault_count_30d','?')}"
            )
    if sections:
        top = sections[0]
        snippet = str(top.get("content", ""))[:400].strip()
        if len(str(top.get("content", ""))) > 400:
            snippet += "..."
        parts.append(f"\nManual reference:\n{snippet}\n— {format_citation(top)}")
    return "\n".join(parts) if parts else (
        "I could not find relevant data. Please consult the Engineering Department."
    )


def _llm_casual(message: str, history: list[dict]) -> str:
    try:
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        messages: list[dict] = [{"role": "system", "content": CASUAL_SYSTEM_PROMPT}]
        for turn in history[-4:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": message})
        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            max_tokens=80,
            messages=messages,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "Hello! I'm your RailSense Maintenance Assistant. Ask me about engine maintenance, brake systems, bogie inspection, or any other railway equipment."


def _llm_chat(message: str, history: list[dict]) -> str:
    try:
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": message})
        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            max_tokens=350,
            messages=messages,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "Hello! I'm the RailSense Maintenance Assistant. Ask me anything about railway equipment maintenance or specific train status."


def _llm_answer(
    message: str,
    sections: list[dict],
    history: list[dict],
    train: Optional[dict] = None,
    asset_data: Optional[dict] = None,
    detected_asset_type: str = "",
) -> str:
    try:
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])

        context_parts = []
        if train and asset_data:
            context_parts.append(_build_asset_context(train, asset_data))
        if sections:
            # Label each section with its source so LLM can judge relevance
            section_note = (
                f"(Note: these sections were retrieved by similarity search for '{detected_asset_type or 'general'}' — "
                "use them only if they are relevant to the question; otherwise answer from your expert knowledge)"
            )
            context_parts.append(f"MANUAL REFERENCE {section_note}:\n" + _build_manual_context(sections))

        context = "\n\n".join(context_parts) if context_parts else "No additional context available."

        user_content = f"Context:\n{context}\n\nEngineer's question: {message}"
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_content})

        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            max_tokens=600,
            messages=messages,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return _template_answer(message, sections, train, asset_data)


def answer_engineer_question(
    message: str,
    asset_type: str = "",
    history: Optional[list[dict]] = None,
    flags: Optional[dict[str, dict]] = None,
    reports: Optional[list[dict]] = None,
) -> dict[str, Any]:
    history = history or []

    # 0. Operational questions ("which trains are unavailable?", "is the Yal Devi running
    # today?") are answered from live flags + latest inspections + open reports, with
    # manual RAG only for assets that show a fault (rag/ops_status.py). Technical
    # questions return None here and continue to manual RAG below.
    from rag.ops_status import answer_ops_question
    ops = answer_ops_question(message, flags or {}, reports or [])
    if ops is not None:
        return ops

    # 0a. Short-circuit: train list query
    if _is_train_list_query(message):
        return {
            "answer": _build_train_list_answer(),
            "citations": [],
            "retrieval_method": "registry",
            "answer_method": "registry",
            "detected_asset_type": "",
            "detected_train": None,
        }

    # 0b. Short-circuit: casual / greeting message — no structured cards
    if _is_casual_message(message):
        casual_answer = _llm_casual(message, history) if os.getenv("GROQ_API_KEY") else \
            "Hello! I'm your RailSense Maintenance Assistant. Ask me about engine maintenance, brake systems, bogie inspection, or any railway equipment."
        return {
            "answer": casual_answer,
            "citations": [],
            "retrieval_method": "none",
            "answer_method": "llm_grounded",
            "detected_asset_type": "",
            "detected_train": None,
        }

    # 1. Detect if question is about a specific train
    train = _detect_train(message)
    asset_data = None
    if train:
        asset_data = _fetch_asset_data(train["loco"])

    # 2. Detect asset type for manual retrieval
    detected_type = asset_type or _detect_asset_type(message)

    # 3. Retrieve relevant manual sections
    sections, retrieval_method = retrieve_manual_sections(
        query=message,
        asset_type=detected_type,
        top_k=5,
    )

    # 3b. Filter sections to those from the matching manual when asset type is known
    _ASSET_MANUAL_MAP = {
        "diesel_engine":  "diesel_engine_manual",
        "electric_loco":  "electric_locomotive_manual",
        "bogie":          "bogie_inspection_guide",
        "brake_system":   "brake_system_manual",
        "signal_unit":    "signal_equipment_manual",
        "track_section":  "track_maintenance_reference",
        "level_crossing": "level_crossing_manual",
        "platform_gate":  "platform_gate_manual",
    }
    if detected_type and detected_type in _ASSET_MANUAL_MAP:
        target_file = _ASSET_MANUAL_MAP[detected_type]
        matching = [s for s in sections if target_file in s.get("source_file", "")]
        # Use matched sections; if none match, clear so LLM uses general knowledge
        sections = matching[:3] if matching else []
    else:
        sections = sections[:3]

    # 4. Generate answer
    if os.getenv("GROQ_API_KEY"):
        if sections or train:
            answer = _llm_answer(message, sections, history, train, asset_data, detected_type)
        else:
            answer = _llm_chat(message, history)
        answer_method = "llm_grounded"
    else:
        answer = _template_answer(message, sections, train, asset_data)
        answer_method = "template_grounded"

    citations = [
        {
            "manual": s.get("manual"),
            "section_title": s.get("section_title"),
            "snippet": str(s.get("content", ""))[:300],
            "source_file": s.get("source_file"),
            "score": s.get("score"),
        }
        for s in sections
    ]

    return {
        "answer": answer,
        "citations": citations,
        "retrieval_method": retrieval_method,
        "answer_method": answer_method,
        "detected_asset_type": detected_type,
        "detected_train": train,
    }
