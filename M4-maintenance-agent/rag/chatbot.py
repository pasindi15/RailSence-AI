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

SYSTEM_PROMPT = """You are an expert railway maintenance engineer assistant for Sri Lanka Railways (SLR).

Always reply using EXACTLY this structure (use the bold labels as shown):

**Status:** One sentence — current condition or direct answer to the question.

**Details:**
- Key finding or fact 1
- Key finding or fact 2
- Key finding or fact 3 (add more if needed)

**Action Required:**
- Step 1 (most urgent first)
- Step 2
- Step 3

**Reference:** Manual section, threshold, or interval that applies.

Rules:
- When fleet/asset data is provided, use it as the PRIMARY source. Cite the asset ID, health score, and status in the Status line.
- When manual context is provided but does NOT match the question topic, IGNORE it and answer from your expert railway engineering knowledge instead. Label the Reference as "General guidance — SLR standard practice".
- When manual context IS relevant, cite it in the Reference line.
- Use only bullet points for lists — no tables, no numbered lists, no markdown headings.
- Be concise. Each bullet should be one clear sentence.
- If a question is outside railway maintenance, say so in the Status line and stop.
- Never leave a section blank — write "None at this time" if nothing applies."""


def _detect_asset_type(message: str) -> str:
    lower = message.lower()
    scores: dict[str, int] = {}
    for asset_type, keywords in ASSET_TYPE_HINTS.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score:
            scores[asset_type] = score
    return max(scores, key=lambda k: scores[k]) if scores else ""


def _detect_train(message: str) -> Optional[dict]:
    """Return train info if the message mentions a known SLR train name."""
    lower = message.lower()
    for name, info in TRAIN_NAME_MAP.items():
        if name in lower:
            return {"name": name.title(), **info}
    # Also match by loco ID or train number
    for name, info in TRAIN_NAME_MAP.items():
        if info["loco"].lower() in lower or info["number"] in lower:
            return {"name": name.title(), **info}
    return None


def _fetch_asset_data(loco_id: str) -> Optional[dict]:
    """Fetch the latest health record for a locomotive from Supabase or CSV."""
    try:
        import supabase_store
        client = supabase_store.get_client()
        if client:
            result = (
                client.table("assets_history")
                .select("*")
                .eq("asset_id", loco_id)
                .order("last_service_date", desc=True)
                .limit(5)
                .execute()
            )
            rows = result.data or []
        else:
            import csv
            data_path = AGENT_DIR / "data" / "assets_history.csv"
            rows = []
            if data_path.exists():
                with open(data_path, encoding="utf-8") as f:
                    rows = [r for r in csv.DictReader(f) if r.get("asset_id") == loco_id]
                rows = rows[-5:]
        if not rows:
            return None
        # Summarise across asset types for this loco
        summary = []
        for r in rows:
            summary.append({
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
            })
        return {"loco_id": loco_id, "records": summary}
    except Exception:
        return None


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
) -> dict[str, Any]:
    history = history or []

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
