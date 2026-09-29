"""
Passenger Assistant Agent - Phase 1
Endpoints: /chat, /feedback, /health

Phase 1 scope:
 - language detection
 - intent classification
 - simple entity extraction
 - simple keyword-based FAQ answer (placeholder for full ChromaDB RAG in Phase 2)
 - hub_client is called but returns a STUB response (real Hub wiring = Phase 3)
"""
import os
import re
import sys
import time
import uuid
import asyncio
import contextvars
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode

# Needed to import the shared/ package (train_repository) from the monorepo
# root, which isn't on sys.path by default when uvicorn runs from backend/.
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Windows' console defaults stdout/stderr to cp1252, which can't encode
# Sinhala/Tamil text. Any print() of passenger input (e.g. the [chat] debug
# logs below) then raises UnicodeEncodeError and 500s the whole request
# before NLU/RAG/Gemini even run. Force UTF-8 so logging never crashes on
# non-ASCII input.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# The on-disk .chroma index is only readable by the chromadb version pinned in
# requirements.txt (currently 1.5.9) - running this process with any other
# Python (e.g. a global interpreter instead of backend/venv) silently loads a
# different chromadb and every RAG retrieval fails with KeyError: '_type'.
# Log both up front so a wrong-interpreter mistake is obvious in the logs
# instead of showing up as "I'm having trouble looking that up right now."
_EXPECTED_CHROMADB_VERSION = "1.5.9"
print(f"[startup] python executable: {sys.executable}")
try:
    import chromadb as _chromadb_check
    print(f"[startup] chromadb version: {_chromadb_check.__version__}")
    print(f"[startup] chromadb location: {_chromadb_check.__file__}")
    if _chromadb_check.__version__ != _EXPECTED_CHROMADB_VERSION:
        print(
            f"[startup] WARNING: chromadb {_chromadb_check.__version__} is loaded, "
            f"but requirements.txt pins {_EXPECTED_CHROMADB_VERSION} (the version the "
            f".chroma index on disk was built with). This process is probably running "
            f"under the wrong Python interpreter - use backend\\venv\\Scripts\\python.exe, "
            f"not a global/system python. RAG retrieval will likely fail with "
            f"KeyError: '_type' until this is fixed."
        )
except ImportError as _e:
    print(f"[startup] WARNING: could not import chromadb to check its version: {_e}")

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client

from nlu.lang_detect import detect_language
from nlu.intent_classifier import classify_intent, is_greeting
from nlu.ner_extractor import STATION_ALIASES, extract_entities
from hub_client import build_envelope, send_to_hub, USE_MOCK_HUB
from i18n import t
from llm_client import build_model
from rag.retriever import retrieve_faq_chunks
from shared.train_repository import TrainRepositoryUnavailable, get_train, get_train_details, get_train_schedule, search_trains

# load_dotenv() with no path searches upward from the CWD, not from this
# file's location - if uvicorn is ever launched from outside backend/, that
# silently finds no .env, GEMINI_API_KEY stays None, and /chat falls back to
# raw RAG chunk text with zero errors. Anchor it to this file instead.
load_dotenv(Path(__file__).parent / ".env")
# Then the repository-root .env for anything not set above. backend/.env is
# git-ignored, so on a teammate's laptop it usually doesn't exist; without this
# fallback M1 started with no Supabase/Gemini keys there while working here.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"[startup] WARNING: Supabase init failed ({e}) — chat history disabled")

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system_prompt.md").read_text(encoding="utf-8")

# LLM is served through OpenRouter (see llm_client.py). The variable keeps its
# historical name `gemini_model` because the answer/guard code and tests use it.
gemini_model = build_model(system_instruction=SYSTEM_PROMPT)
if gemini_model:
    print(f"[startup] OPENROUTER_API_KEY loaded - LLM ready: {gemini_model.model}")
else:
    print("[startup] WARNING: OPENROUTER_API_KEY not set (or openai not installed) - /chat will fall back to raw RAG chunk text, not LLM answers")

app = FastAPI(title="RailSense AI - Passenger Assistant Agent")

# Allow the frontend (running on a different port) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this before final submission
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    intent: str
    language: str
    entities: dict
    source: str
    delay_minutes: float | None = None
    action: dict | None = None
    prefill: dict | None = None
    cancellation: dict | None = None


class FeedbackRequest(BaseModel):
    session_id: str
    rating: int
    comment: str | None = None


class SessionSummary(BaseModel):
    session_id: str
    title: str
    is_pinned: bool
    created_at: str
    updated_at: str


class PinRequest(BaseModel):
    pinned: bool


class TitleRequest(BaseModel):
    title: str


# Matches crypto.randomUUID() from the frontend (and str(uuid.uuid4()) from the
# ChatRequest default). Rejecting anything else before it reaches a Supabase
# filter keeps session_id out of query-building entirely, not just escaped.
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def validate_session_id(session_id: str) -> None:
    if not SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")


# ── Quick chat (the "Choo" widget) ───────────────────────────────────
# Choo is the ask-and-go assistant on the passenger pages. It runs this exact
# same pipeline - language detection, intent, NER, RAG, the Hub agents and the
# LLM - so its answers are the full Passenger Assistant's answers. The only
# difference is that nothing is written to Supabase, so a quick question never
# creates a chat_sessions row, never lands in chat_messages, and therefore
# never shows up in the sidebar list (GET /chat) or in
# GET /chat/{session_id}/history.
#
# POST /chat/quick sets this flag for the duration of one request; every
# Supabase read/write helper below checks it and uses the in-process buffer
# instead, so follow-ups ("...and for 3 passengers?") still work within a visit
# without anything being stored.
_quick_chat: contextvars.ContextVar[bool] = contextvars.ContextVar("quick_chat", default=False)

# 4 turns - deliberately below SUMMARY_EVERY, so the rolling-summary path (which
# would call the LLM again and write chat_summaries) never triggers for Choo.
QUICK_MAX_MESSAGES = 8
QUICK_TTL_SECONDS = 30 * 60
QUICK_MAX_SESSIONS = 500
# session_id -> {"messages": [{"role", "message"}, ...], "seen": monotonic seconds}
_quick_messages: dict[str, dict] = {}


def _quick_prune() -> None:
    """Drop stale visitors so a public widget can't grow this dict forever."""
    cutoff = time.monotonic() - QUICK_TTL_SECONDS
    for sid in [s for s, v in _quick_messages.items() if v["seen"] < cutoff]:
        _quick_messages.pop(sid, None)
    while len(_quick_messages) > QUICK_MAX_SESSIONS:
        _quick_messages.pop(min(_quick_messages, key=lambda s: _quick_messages[s]["seen"]), None)


def _quick_remember(session_id: str, role: str, message: str) -> None:
    _quick_prune()
    entry = _quick_messages.setdefault(session_id, {"messages": [], "seen": 0.0})
    entry["messages"] = (entry["messages"] + [{"role": role, "message": message}])[-QUICK_MAX_MESSAGES:]
    entry["seen"] = time.monotonic()


def _quick_history(session_id: str) -> list[dict]:
    return list(_quick_messages.get(session_id, {}).get("messages", []))


def get_recent_history(session_id: str, turns: int = 3) -> list[dict]:
    """Last `turns` conversation turns (user+assistant pairs) for this session, oldest first."""
    if _quick_chat.get():
        return _quick_history(session_id)[-turns * 2:]
    if not supabase:
        return []
    try:
        result = (
            supabase.table("chat_messages")
            .select("role,message")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(turns * 2)
            .execute()
        )
        return list(reversed(result.data))
    except Exception as e:
        print(f"Supabase history fetch failed: {e}")
        return []


# ── Rolling conversation memory ──────────────────────────────────────
# Every SUMMARY_EVERY completed turns (a turn = user message + reply) the older
# part of the chat is folded into a running summary. The prompt then carries
# that summary plus every turn after it verbatim, so the model always sees the
# whole chat: fewer than 5 turns -> all verbatim; more -> summary + recent.
# Kept in process memory; if lost (restart) it is rebuilt from chat_messages.
SUMMARY_EVERY = 5
MAX_HISTORY_MESSAGES = 200
_session_summaries: dict[str, dict] = {}  # session_id -> {"summary": str, "turns": int}


def _fetch_all_messages(session_id: str) -> list[dict]:
    if _quick_chat.get():
        return _quick_history(session_id)
    if not supabase:
        return []
    try:
        result = (
            supabase.table("chat_messages")
            .select("role,message")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(MAX_HISTORY_MESSAGES)
            .execute()
        )
        return list(reversed(result.data))
    except Exception as e:
        print(f"[context] history fetch failed: {e}")
        return []


def _load_summary(session_id: str) -> dict | None:
    """Stored summary row for the session, or None."""
    if _quick_chat.get():
        return None
    if not supabase:
        return None
    try:
        result = (
            supabase.table("chat_summaries")
            .select("summary,turns_covered")
            .eq("session_id", session_id)
            .limit(1)
            .execute()
        )
        if result.data:
            row = result.data[0]
            return {"summary": row["summary"], "turns": row["turns_covered"]}
    except Exception as e:
        print(f"[context] summary load failed (does chat_summaries exist?): {e}")
    return None


def _save_summary(session_id: str, state: dict) -> None:
    if _quick_chat.get():
        return
    if not supabase:
        return
    try:
        supabase.table("chat_summaries").upsert({
            "session_id": session_id,
            "summary": state["summary"],
            "turns_covered": state["turns"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        print(f"[context] session={session_id} summary saved to DB (turns_covered={state['turns']})")
    except Exception as e:
        print(f"[context] summary save failed (does chat_summaries exist?): {e}")


def _split_turns(messages: list[dict]) -> list[list[dict]]:
    """Group messages into turns, each starting at a user message."""
    turns: list[list[dict]] = []
    for m in messages:
        if m["role"] == "user" or not turns:
            turns.append([m])
        else:
            turns[-1].append(m)
    return turns


def _format_turns(turns: list[list[dict]]) -> str:
    return "\n".join(f"{m['role']}: {m['message']}" for turn in turns for m in turn)


def _summarize_turns(previous: str, turns: list[list[dict]]) -> str:
    """Fold `turns` into the running summary. LLM when available, else a plain digest."""
    transcript = _format_turns(turns)
    if gemini_model:
        prompt = (
            "Summarize this railway passenger chat so an assistant can continue it later. "
            "Keep concrete details: stations, train names/ids, dates, times, passenger counts, "
            "seat classes, bookings, fares quoted, complaints, unresolved questions and the "
            "passenger's language. Max 120 words, plain text, no preamble.\n\n"
            f"Existing summary (may be empty):\n{previous or '(none)'}\n\n"
            f"New conversation turns to add:\n{transcript}"
        )
        try:
            text = (gemini_model.generate_content(prompt).text or "").strip()
            if text:
                return text
        except Exception as e:
            print(f"[context] LLM summary failed ({type(e).__name__}): {e} - using plain digest")
    digest = " | ".join(f"Q: {t[0]['message'][:120]}" for t in turns)
    return f"{previous} | {digest}".strip(" |")[-1200:]


def get_conversation_context(session_id: str) -> tuple[str, str]:
    """Return (summary, recent_verbatim_text) for the session's prior turns."""
    if _quick_chat.get():
        # Quick chat keeps at most QUICK_MAX_MESSAGES in memory, which is short
        # enough to send verbatim - no summary to build, and nothing is cached in
        # _session_summaries (that dict is keyed by session and would otherwise
        # outlive the visit).
        return "", _format_turns(_split_turns(_fetch_all_messages(session_id)))

    turns = _split_turns(_fetch_all_messages(session_id))
    total = len(turns)
    covered_target = (total // SUMMARY_EVERY) * SUMMARY_EVERY
    state = _session_summaries.get(session_id)
    if state is None:
        state = _load_summary(session_id) or {"summary": "", "turns": 0}
        _session_summaries[session_id] = state
        if state["turns"]:
            print(f"[context] session={session_id} summary loaded from DB (turns_covered={state['turns']})")

    if covered_target > state["turns"]:
        new_turns = turns[state["turns"]:covered_target]
        print(f"[context] session={session_id} summarizing turns {state['turns'] + 1}-{covered_target} of {total}")
        state = {"summary": _summarize_turns(state["summary"], new_turns), "turns": covered_target}
        _session_summaries[session_id] = state
        _save_summary(session_id, state)
        print(f"[context] session={session_id} new summary: {state['summary']!r}")

    recent = _format_turns(turns[state["turns"]:])
    print(
        f"[context] session={session_id} turns={total} summarized={state['turns']} "
        f"verbatim={total - state['turns']} has_summary={bool(state['summary'])}"
    )
    return state["summary"], recent


# fare_query / schedule_query map 1:1 to a doc, so retrieval can skip
# straight to it instead of relying on embedding similarity to pick the
# right file (e.g. "train fare" otherwise ranks schedules.md over fares.md).
INTENT_SOURCE_DOC = {
    "fare_query": "fares.md",
    "schedule_query": "schedules.md",
    "policy_query": "policies.md",
}

LANGUAGE_NAMES = {"si": "Sinhala", "ta": "Tamil", "en": "English"}

# One explicit sentence per detected language, placed at the top of every Gemini
# prompt (see compose_rag_answer). Gemini generates the answer directly in this
# language from the retrieved context - the reply is never translated afterwards.
LANGUAGE_ANSWER_RULES = {
    "si": "Answer completely in Sinhala.",
    "ta": "Answer completely in Tamil.",
    "en": "Answer in English.",
}

_SCRIPT_RANGES = {"si": (0x0D80, 0x0DFF), "ta": (0x0B80, 0x0BFF)}


def _has_script(text: str, language: str) -> bool:
    lo, hi = _SCRIPT_RANGES[language]
    return any(lo <= ord(ch) <= hi for ch in text)


# --- Language-aware fallback (used only when Gemini is unavailable) -----------
# If Gemini is not configured, errors (e.g. 429 quota) or returns nothing, the
# passenger still gets the RAG facts. English keeps the original wording; for
# Sinhala/Tamil the fixed frame is localized. Fare data is structured, so it is
# rendered fully in the passenger's language. Policy/schedule text is free-form
# English that cannot be translated without the LLM, so it is shown after a
# localized notice saying it is temporarily English-only - never silently.
FALLBACK_STRINGS = {
    "si": {
        "found": "මට හමු වූ තොරතුරු:",
        "found_group": "මගීන් {n} දෙනෙකු සඳහා මට හමු වූ තොරතුරු:",
        "seat_line": "{label}: ආසනයකට LKR {amt}",
        "person_line": "{label}: එක් අයෙකුට LKR {amt}",
        "group_line": "{label}: LKR {amt} × {n} = LKR {total}",
        "both_ways": "දෙදිශාවටම එකම ගාස්තුවක් අදාළ වේ.",
        "class_missing": "මෙම මාර්ගය සඳහා \"{requested}\" ගාස්තුවක් ලැයිස්තුගත කර නැත. පවතින ගාස්තු:",
        "english_only_notice": (
            "පිළිතුර සකස් කරන සේවාව දැනට තාවකාලිකව නොමැති බැවින්, "
            "මෙම තොරතුරු දැනට ඉංග්‍රීසියෙන් පමණක් පෙන්වයි:"
        ),
    },
    "ta": {
        "found": "எனக்குக் கிடைத்த தகவல்:",
        "found_group": "{n} பயணிகளுக்குக் கிடைத்த தகவல்:",
        "seat_line": "{label}: ஒரு இருக்கைக்கு LKR {amt}",
        "person_line": "{label}: ஒருவருக்கு LKR {amt}",
        "group_line": "{label}: LKR {amt} × {n} = LKR {total}",
        "both_ways": "இரு திசைகளிலும் ஒரே கட்டணம் பொருந்தும்.",
        "class_missing": "இந்த வழித்தடத்திற்கு \"{requested}\" கட்டணம் பட்டியலிடப்படவில்லை. கிடைக்கும் கட்டணங்கள்:",
        "english_only_notice": (
            "பதிலைத் தயாரிக்கும் சேவை தற்போது தற்காலிகமாகக் கிடைக்காததால், "
            "இந்தத் தகவல் தற்போது ஆங்கிலத்தில் மட்டும் காட்டப்படுகிறது:"
        ),
    },
}

# Display names for the booking system's canonical class names (fares.md labels).
FARE_CLASS_LABELS = {
    "si": {"First Class": "පළමු පන්තිය", "Second Class": "දෙවන පන්තිය"},
    "ta": {"First Class": "முதல் வகுப்பு", "Second Class": "இரண்டாம் வகுப்பு"},
}


def _station_display(name: str, language: str) -> str:
    """Localized station name: the first alias in STATION_ALIASES written in the
    passenger's script (the canonical English name if there is none)."""
    for alias in STATION_ALIASES.get(name, []):
        if _has_script(alias, language):
            return alias
    return name


def _disp(name: str | None, language: str) -> str | None:
    """A station name as the passenger should see it (Sinhala/Tamil script for si/ta)."""
    if not name or language not in _SCRIPT_RANGES:
        return name
    return _station_display(name, language)


def _language_prompt_block(language: str) -> str:
    """The language instruction + factual-grounding rules placed at the top of EVERY
    Gemini prompt (RAG answers and agent-result answers alike), so the language
    detected once in /chat controls the language of whatever Gemini writes."""
    language_name = LANGUAGE_NAMES.get(language, "English")
    instruction = (
        f"Detected passenger language: {language_name} ({language}). "
        f"You must answer the passenger in the detected language. "
        f"{LANGUAGE_ANSWER_RULES.get(language, LANGUAGE_ANSWER_RULES['en'])} "
        f"Respond only in {language_name}."
    )
    # Restated on every turn (the system prompt has the same rules) so the model
    # is directed to it for this specific question.
    rules = (
        "Answer rules for this reply: state railway facts ONLY from the retrieved "
        "knowledge base context, the agent result, the extracted details and the "
        "pre-computed values below; never invent or change a fare, train number, "
        "time, delay or route. Keep train IDs, booking references, times and "
        "currency amounts (e.g. LKR 2500) exactly as given; station names may be "
        f"written in {language_name}. Do not mention the knowledge base, agents, "
        "JSON or any other internal detail, and do not output JSON - write a "
        "natural, passenger-friendly answer."
    )
    return f"{instruction}\n\n{rules}"


def present_agent_result(
    language: str, question: str, label: str, facts: dict, required: list[str]
) -> str | None:
    """Sinhala/Tamil only: Gemini writes the passenger reply directly in the
    detected language from an agent's structured result (no English-then-translate
    step). Returns None - and the caller uses its deterministic localized template -
    when Gemini is unavailable, errors, returns nothing, answers in the wrong
    script, or drops any value in `required` (IDs / numbers that must survive
    verbatim). English keeps the existing deterministic wording."""
    if language not in _SCRIPT_RANGES or not gemini_model:
        return None
    facts_text = "\n".join(f"- {k}: {v}" for k, v in facts.items() if v not in (None, ""))
    prompt = (
        f"{_language_prompt_block(language)}\n\n"
        "The facts below come from a railway system agent and are the ONLY source of "
        "facts for this reply. Report every number, ID and time exactly. Where a fact "
        "says it is historical or an estimate, say so plainly - never present it as a "
        "live status.\n\n"
        f"Agent result ({label}):\n{facts_text}\n\n"
        f"Passenger's question: {question}\n\nWrite the reply to the passenger now."
    )
    print(f"[llm] Gemini request started for agent result ({label}, language={language})")
    try:
        answer = (gemini_model.generate_content(prompt).text or "").strip()
    except Exception as e:
        print(f"[llm] ERROR - Gemini failed presenting {label} ({type(e).__name__}): {e} - using localized template")
        return None
    if not answer:
        print(f"[llm] ERROR - Gemini returned an empty reply for {label} - using localized template")
        return None
    if not _has_script(answer, language):
        print(f"[llm] WARNING - reply for {label} is not in {LANGUAGE_NAMES[language]} - using localized template")
        return None
    missing = [tok for tok in required if tok not in answer]
    if missing:
        print(f"[llm] WARNING - reply for {label} dropped required value(s) {missing} - using localized template")
        return None
    print(f"[llm] Gemini agent-result reply received ({len(answer)} chars)")
    return answer


def _agent_error(language: str, hub_response) -> str:
    """Truthful, localized message for a failed Hub call. "rejected" = the agent
    answered but could not complete the request; anything else = not reachable.
    The raw technical Hub message is never shown to the passenger."""
    kind = getattr(hub_response, "error_kind", None)
    return t("agent_rejected" if kind == "rejected" else "agent_unreachable", language)

# Fixed, non-LLM replies for FIX 1 (greetings) - deliberately not a Gemini
# call, so this stays instant and free even under load. Written per-language
# rather than relying on translation at request time, matching FIX 4's "no
# English fallback" requirement for the small set of canned reply paths.
GREETING_REPLIES = {
    "en": "Hi! I'm the Sri Lanka Railways assistant — I can help with schedules, fares, delays, or booking. What do you need?",
    "si": "ආයුබෝවන්! මම ශ්‍රී ලංකා දුම්රිය සහායකයා — කාලසටහන්, ගාස්තු, ප්‍රමාදවීම් හෝ වෙන්කිරීම් සම්බන්ධයෙන් මට ඔබට උදව් කළ හැක. ඔබට අවශ්‍ය කුමක්ද?",
    "ta": "வணக்கம்! நான் இலங்கை ரயில்வே உதவியாளர் — அட்டவணைகள், கட்டணங்கள், தாமதங்கள் அல்லது முன்பதிவு குறித்து உங்களுக்கு உதவ முடியும். உங்களுக்கு என்ன தேவை?",
}

# Fixed "not a service of this system" notice for questions that are not about
# this railway's passenger services. Deliberately a canned, in-language message
# rather than something the LLM composes: the limit is a property of the system,
# so it must read the same every time and can never turn into a general-knowledge
# answer (FIX 3 used to only *ask* the LLM to decline).
OUT_OF_SCOPE_REPLIES = {
    "en": (
        "This service only supports Sri Lanka Railways passenger services: train schedules, "
        "fares, booking and cancellation, refund and travel policies, train delays and status, "
        "and reporting a problem. Your question is outside what this system provides, so I can't answer it."
    ),
    "si": (
        "මෙම සේවාව මගින් ශ්‍රී ලංකා දුම්රිය මගී සේවා සම්බන්ධයෙන් පමණක් උදව් කළ හැක: දුම්රිය කාලසටහන්, "
        "ගාස්තු, වෙන්කිරීම් සහ අවලංගු කිරීම්, ආපසු ගෙවීම් සහ ගමන් ප්‍රතිපත්ති, දුම්රිය ප්‍රමාද සහ තත්ත්වය, "
        "සහ ගැටලු වාර්තා කිරීම. ඔබේ ප්‍රශ්නය මෙම පද්ධතිය සපයන සේවාවෙන් පිටත බැවින් මට පිළිතුරු දිය නොහැක."
    ),
    "ta": (
        "இந்தச் சேவை இலங்கை ரயில்வேயின் பயணிகள் சேவைகளுக்கு மட்டுமே உதவும்: ரயில் அட்டவணைகள், கட்டணங்கள், "
        "முன்பதிவு மற்றும் ரத்து, பணத்திரும்பப் பெறுதல் மற்றும் பயணக் கொள்கைகள், ரயில் தாமதம் மற்றும் நிலை, "
        "மற்றும் பிரச்சனையைப் புகாரளித்தல். உங்கள் கேள்வி இந்த அமைப்பு வழங்கும் சேவைகளுக்கு வெளியே உள்ளதால் என்னால் பதிலளிக்க முடியாது."
    ),
}

# Engineering / maintenance-manual questions belong to the Maintenance Agent and
# are engineer-facing only. The passenger assistant never forwards them to it
# and never answers from manual content.
ENGINEERING_NOTICE_REPLIES = {
    "en": (
        "Technical maintenance and engineering information is not available through the passenger "
        "assistant. If you have noticed a fault while travelling, describe it (and the train ID if you "
        "know it) and I will report it to the maintenance team."
    ),
    "si": (
        "තාක්ෂණික නඩත්තු සහ ඉංජිනේරු තොරතුරු මගී සහායක හරහා ලබා ගත නොහැක. ගමන අතරතුර දෝෂයක් දුටුවේ නම්, "
        "එය (දුම්රිය හැඳුනුම් අංකය දන්නේ නම් එයද) විස්තර කරන්න; මම එය නඩත්තු කණ්ඩායමට වාර්තා කරන්නෙමි."
    ),
    "ta": (
        "தொழில்நுட்பப் பராமரிப்பு மற்றும் பொறியியல் தகவல்கள் பயணிகள் உதவியாளர் மூலம் கிடைக்காது. பயணத்தின் போது "
        "ஏதேனும் கோளாறைக் கவனித்திருந்தால், அதை (தெரிந்தால் ரயில் அடையாள எண்ணுடன்) விவரிக்கவும்; "
        "நான் அதைப் பராமரிப்புக் குழுவிற்குத் தெரிவிக்கிறேன்."
    ),
}

# The passenger named a route that has no fare in fares.md (which mirrors the
# booking system's fare table). Say so instead of quoting a different route's fare.
FARE_NOT_AVAILABLE_REPLIES = {
    "en": (
        "I don't have a confirmed fare for that route in the booking system's fare table, so I can't "
        "quote one. Please check at a staffed station counter, or ask me about another route."
    ),
    "si": (
        "එම මාර්ගය සඳහා වෙන්කිරීමේ පද්ධතියේ ගාස්තු වගුවේ තහවුරු කළ ගාස්තුවක් මා සතුව නැති නිසා මට එය ලබා දිය නොහැක. "
        "කරුණාකර සේවක පහසුකම් සහිත දුම්රිය ස්ථාන කවුන්ටරයෙන් විමසන්න, නැතහොත් වෙනත් මාර්ගයක් ගැන අසන්න."
    ),
    "ta": (
        "அந்த வழித்தடத்திற்கு முன்பதிவு அமைப்பின் கட்டண அட்டவணையில் உறுதிப்படுத்தப்பட்ட கட்டணம் என்னிடம் இல்லை, "
        "எனவே அதைத் தர இயலாது. பணியாளர்கள் உள்ள நிலைய கவுண்டரில் விசாரிக்கவும், அல்லது வேறு வழித்தடம் பற்றிக் கேளுங்கள்."
    ),
}

# delay_check is Hub-routed and, per this project's established rule, its
# successful reply is assembled from Operations' own structured fields and
# never re-run through Gemini - so the "Expected delay: ..." reply itself
# stays whatever language the Hub returns (currently English-only on M2's
# side, out of scope here). This only localizes the *local* fallback text
# used when the Hub can't be reached at all.
DELAY_UNREACHABLE_REPLIES = {
    "en": "I couldn't reach the Operations Agent right now.",
    "si": "දැනට මෙහෙයුම් නියෝජිතයා අමතන්නට නොහැකි විය.",
    "ta": "இப்போது இயக்க முகவரை தொடர்பு கொள்ள முடியவில்லை.",
}

# Calibrated against this project's embedding model (all-MiniLM-L6-v2) and
# FAQ set, and ONLY applied when source_filter is None (see below) - a query
# already keyword-classified as fare_query/schedule_query always searches
# with a source_filter set, so it never hits this check at all; the keyword
# match already confirmed it's on-topic. For the unclassified ("unknown"
# intent) path this guards: on-topic-but-vaguely-phrased questions (e.g.
# "can children travel free") measured ~0.99-1.56 against the full FAQ set;
# clearly off-topic ones (weather, poems, trivia - bare greetings are caught
# separately by FIX 1 before ever reaching here) measured ~1.74-1.90. 1.6
# sits in that gap with margin on both sides. A single-station fare/schedule
# query like "how much to Kandy" scores much worse (~1.4-1.8) purely because
# a lone station name is a weak embedding query - that's exactly why this
# check is skipped once intent_classifier has already confirmed relevance
# via keywords, rather than re-litigating topicality on embedding distance
# alone for every intent.
RAG_DISTANCE_THRESHOLD = 1.6

# Distance alone is not enough: a station name in an unrelated question ("best
# restaurants in Colombo") makes the retrieval query just "Colombo Fort", which
# embeds very close to a fare/schedule chunk. In the unclassified path the
# message must therefore also contain a railway-domain word or name a full route
# (two stations), otherwise it is out of scope. Not applied to any question a
# keyword/policy intent already claimed (those pass a source_filter).
RAILWAY_VOCAB = re.compile(
    r"\b(?:trains?|railways?|rail|stations?|platforms?|tickets?|fares?|seats?|book\w*|reserv\w*|"
    r"refund\w*|cancel\w*|luggage|baggage|journey|travel\w*|schedules?|timetable|departs?|"
    r"departure|arrival|delay\w*|late|compartment|coach|carriage|passengers?|route|slr|"
    r"discount\w*|concession\w*|senior|child|children|student|class|complain\w*|polic\w+|"
    r"id|nic|identity)\b",
    re.IGNORECASE,
)
# Sinhala/Tamil railway terms (substring match - these scripts have no \b and
# words are inflected, e.g. දුම්රිය / දුම්රියේ). The embedding model is
# English-centric, so for si/ta the retrieval distance cannot separate on-topic
# from off-topic (measured: a Tamil weather question 1.40, a Tamil luggage
# question 1.93); this vocabulary is the only usable in-scope signal there.
RAILWAY_VOCAB_SI_TA = (
    # Sinhala: train, ticket, fare, price, time, timetable, station, booking, cancel,
    # refund, journey, passenger, delay, luggage, complaint, seat, platform
    "දුම්රිය", "ටිකට්", "ගාස්තු", "මිල", "වේලාව", "වේලාසටහන", "ස්ථාන", "වෙන්", "අවලංගු",
    "ආපසු ගෙවී", "ගමන", "මගී", "ප්‍රමාද", "බඩු", "පැමිණිල්ල", "පැමිණිලි", "ආසන", "වේදිකා",
    # Tamil
    "ரயில்", "டிக்கெட்", "கட்டணம்", "விலை", "நேரம்", "அட்டவணை", "நிலையம்", "முன்பதிவு", "ரத்து",
    "பணத்திரும்ப", "பணம் திரும்ப", "பயண", "பயணி", "தாமத", "லக்கேஜ்", "சாமான்", "புகார்", "இருக்கை", "நடைமேடை",
)


def _mentions_railway(text: str, language: str) -> bool:
    if language == "en":
        return bool(RAILWAY_VOCAB.search(text))
    return any(term in text for term in RAILWAY_VOCAB_SI_TA)

# Matches a fare doc line like "- 2nd Class Reserved: LKR 500".
FARE_LINE_PATTERN = re.compile(r"^-\s*(?P<label>[^:]+):\s*LKR\s*(?P<amount>[\d,]+)", re.MULTILINE)


def _label_matches_fare_class(label: str, class_keywords: list[str]) -> bool:
    """True if every requested keyword ("1st"/"2nd"/"3rd"/"ac"/"reserved"/
    "unreserved"/"observation saloon") appears in the fare line's label as a
    whole word. Word-boundary matching (not a plain substring check) matters
    here specifically because "reserved" is a literal substring of
    "unreserved" - a naive `in` check would make "2nd class reserved" also
    match the "2nd Class Unreserved" line, which is exactly the bug this is
    fixing."""
    lowered_label = label.lower()
    return all(re.search(rf"\b{re.escape(kw)}\b", lowered_label) for kw in class_keywords)


def _matching_fare_lines(chunks: list[dict], class_keywords: list[str]) -> list[tuple[str, int]]:
    """All (label, per_person_amount) fare lines from the retrieved chunks, in
    order, narrowed to class_keywords when given. Deliberately not
    deduplicated by label - retrieval can (and does) pull in more than one
    route's section at once, and different routes reuse the same class label
    (e.g. "2nd Class Reserved") at different prices, so collapsing by label
    would silently keep one route's price and drop another's."""
    lines: list[tuple[str, int]] = []
    for chunk in chunks:
        for m in FARE_LINE_PATTERN.finditer(chunk["text"]):
            label = m.group("label").strip()
            if class_keywords and not _label_matches_fare_class(label, class_keywords):
                continue
            lines.append((label, int(m.group("amount").replace(",", ""))))
    return lines


def _compute_group_fares(chunks: list[dict], passenger_count: int, class_keywords: list[str] | None = None) -> str:
    """Multiply every matching per-person 'LKR N' fare line found in the
    retrieved fare chunks by passenger_count, in code. The LLM is instructed
    to use these totals verbatim in its reply instead of doing the
    multiplication itself - it isn't reliable at arithmetic and shouldn't be
    trusted to get it right."""
    lines = []
    for label, per_person in _matching_fare_lines(chunks, class_keywords or []):
        total = per_person * passenger_count
        lines.append(f"- {label}: LKR {per_person} x {passenger_count} passengers = LKR {total}")
    return "\n".join(lines)


def _chunk_body(text: str, limit: int = 1500) -> str:
    """A retrieved chunk as passenger-readable text for the no-LLM fallback: drop
    the document-title line that embed_documents prefixes to every chunk, show the
    section heading in bold, and cut at a line boundary rather than mid-sentence
    (a fixed 400-char cut used to drop the very facts - e.g. refund percentages -
    that the passenger asked about)."""
    parts = text.split("\n\n", 1)
    body = parts[1] if len(parts) == 2 else text
    lines = body.splitlines()
    if lines and lines[0].startswith("## "):
        lines[0] = f"**{lines[0][3:].strip()}**"
    out, size = [], 0
    for line in lines:
        if out and size + len(line) > limit:
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


def _localized_fare_chunk(chunk: dict, language: str) -> str:
    """One fares.md route section rendered in Sinhala/Tamil. Route and class names
    are localized; LKR amounts are copied unchanged from the chunk."""
    t = FALLBACK_STRINGS[language]
    route = " - ".join(_station_display(part.strip(), language) for part in chunk["heading"].split(" - "))
    lines = [f"**{route}**"]
    for m in FARE_LINE_PATTERN.finditer(chunk["text"]):
        label = m.group("label").strip()
        lines.append("• " + t["seat_line"].format(
            label=FARE_CLASS_LABELS[language].get(label, label), amt=m.group("amount")))
    if "same fare in both directions" in chunk["text"].lower():
        lines.append(t["both_ways"])
    return "\n".join(lines)


# schedules.md service lines look like "- Podi Menike (1005): departs 05:55, arrives 08:47"
# or "- Ruhunu Kumari (50): departs Maradana 05:50, arrives Matara 09:10". The
# structure is regular, so a Sinhala/Tamil schedule answer can be rendered without
# any translation of schedules.md: train names, numbers and times are copied as-is,
# only the labels and known station names are localized.
_SCHEDULE_LINE = re.compile(
    r"^-\s*(?P<name>.+?)\s*\((?P<code>[^)]*)\):\s*departs\s+(?P<dep>.+?),\s*arrives\s+(?P<arr>.+?)\s*$"
)
_CLOCK = re.compile(r"\d{1,2}:\d{2}")
SCHEDULE_STRINGS = {
    "si": {"departs": "පිටත්වීම", "arrives": "පැමිණීම", "overnight": "(රාත්‍රී ගමන)"},
    "ta": {"departs": "புறப்பாடு", "arrives": "வருகை", "overnight": "(இரவுப் பயணம்)"},
}


def _place_time(fragment: str, language: str) -> str:
    """"Maradana 05:50" -> "<localized Maradana> 05:50"; "05:50" stays "05:50"."""
    m = _CLOCK.search(fragment)
    if not m:
        return fragment
    place = fragment[: m.start()].strip()
    return f"{_disp(place, language) if place else ''} {fragment[m.start():]}".strip()


_HEADING_ROUTE = re.compile(r"^(?P<line>.+?)\s+—\s+(?P<a>.+?)\s+to\s+(?P<b>.+)$")


def _localize_heading(heading: str, language: str) -> str:
    """"Main Line — Colombo Fort to Kandy" -> "Main Line — <si/ta Colombo Fort> - <si/ta Kandy>".
    The line name is a proper noun and stays; only known station names change script."""
    m = _HEADING_ROUTE.match(heading)
    if m and m["a"] in STATION_ALIASES and m["b"] in STATION_ALIASES:
        return f"{m['line']} — {_disp(m['a'], language)} - {_disp(m['b'], language)}"
    return heading


def _localized_schedule_chunk(chunks: list[dict], stations: list[str], language: str) -> str:
    """The schedules.md section for the asked route (first section naming every
    asked station, else the best-ranked one), rendered in the passenger's language."""
    strings = SCHEDULE_STRINGS[language]
    ranked = [c for c in chunks if all(s.lower() in c["heading"].lower() for s in stations)] if stations else []
    for chunk in ranked + list(chunks):
        lines = []
        for raw in chunk["text"].splitlines():
            m = _SCHEDULE_LINE.match(raw.strip())
            if not m:
                continue
            arr = _place_time(m.group("arr"), language).replace("(overnight)", strings["overnight"])
            lines.append(
                f"• {m.group('name')} ({m.group('code')}): "
                f"{strings['departs']} {_place_time(m.group('dep'), language)}, {strings['arrives']} {arr}"
            )
        if lines:
            return "**" + _localize_heading(chunk["heading"], language) + "**" + chr(10) + chr(10).join(lines)
    return ""


def _localized_fallback_text(
    language: str,
    intent: str,
    chunks: list[dict],
    fare_chunks: list[dict],
    fare_class_keywords: list[str],
    passenger_count: int | None,
    stations: list[str] | None = None,
) -> str | None:
    """No-LLM fallback in the passenger's language, or None for English (the
    original English fallback wording is kept unchanged)."""
    t = FALLBACK_STRINGS.get(language)
    if t is None:
        return None
    labels = FARE_CLASS_LABELS[language]

    def group_lines(matched):
        return "\n".join(
            "• " + t["group_line"].format(label=labels.get(label, label), amt=amt, n=passenger_count, total=amt * passenger_count)
            for label, amt in matched
        )

    if intent == "fare_query":
        if fare_class_keywords:
            matched = _matching_fare_lines(fare_chunks, fare_class_keywords)
            if matched and passenger_count and passenger_count > 1:
                return f"{t['found_group'].format(n=passenger_count)}\n\n{group_lines(matched)}"
            if matched:
                lines = "\n".join(
                    "• " + t["person_line"].format(label=labels.get(label, label), amt=amt) for label, amt in matched
                )
                return f"{t['found']}\n\n{lines}"
            requested = " ".join(fare_class_keywords)
            route_chunk = next((c for c in fare_chunks if FARE_LINE_PATTERN.search(c["text"])), None)
            body = _localized_fare_chunk(route_chunk, language) if route_chunk else ""
            return f"{t['class_missing'].format(requested=requested)}\n\n{body}".strip()
        if passenger_count and passenger_count > 1:
            matched = _matching_fare_lines(fare_chunks, [])
            if matched:
                return f"{t['found_group'].format(n=passenger_count)}\n\n{group_lines(matched)}"
        route_chunk = next((c for c in fare_chunks if FARE_LINE_PATTERN.search(c["text"])), None)
        if route_chunk:
            return f"{t['found']}\n\n{_localized_fare_chunk(route_chunk, language)}"
    if intent == "schedule_query":
        schedule = _localized_schedule_chunk(chunks, stations or [], language)
        if schedule:
            return t["found"] + chr(10) * 2 + schedule
    # Policy / anything free-form: only English source text exists.
    return f"{t['english_only_notice']}\n\n{_chunk_body(chunks[0]['text'])}"


def compose_rag_answer(
    text: str,
    language: str,
    session_id: str,
    source_filter: str | None = None,
    intent: str = "unknown",
    entities: dict | None = None,
) -> tuple[str, str]:
    """Retrieve top FAQ chunks and have Gemini compose a grounded natural-language reply."""
    # The embedding model is English-centric, so embedding a Sinhala/Tamil
    # question directly makes retrieval ranking close to random - even
    # between the right document section and an unrelated one (e.g. Kandy
    # vs. Badulla both under fares.md). NER already resolves station names
    # to their canonical English form regardless of input language, so use
    # those for the retrieval query when available instead of the raw text.
    entity_stations = (entities or {}).get("stations") or []
    retrieval_query = " to ".join(entity_stations) if entity_stations else text

    try:
        chunks = retrieve_faq_chunks(retrieval_query, top_k=3, source_filter=source_filter)
    except Exception as e:
        # A retrieval-layer failure (e.g. a chromadb version/data mismatch) must not
        # 500 the whole /chat endpoint or leak internals to the passenger - log the
        # real exception and degrade to a clean message instead.
        print(f"[rag] ERROR - retrieval failed ({type(e).__name__}): {e}")
        return t("rag_error", language), ""
    print(f"[rag] retrieved {len(chunks)} chunk(s) for query={retrieval_query!r} (original text={text!r}) source_filter={source_filter!r}")
    if not chunks:
        print(f"[offtopic] intent={intent} query={text!r} reason=no_chunks_retrieved")
        return t("rag_no_chunks", language), ""

    # Off-topic guardrail (FIX 3): even the closest match being a weak one
    # means the retrieved chunks aren't actually relevant to this question
    # (e.g. "what's the weather" still returns *some* chunk - ChromaDB always
    # returns its top-k - just not a relevant one). Without this check the
    # LLM would see that irrelevant chunk plus its own general knowledge and
    # could still "answer" instead of declining. Only checked when
    # source_filter is unset (the "unknown" intent path) - fare_query/
    # schedule_query already searched with a source_filter, meaning
    # intent_classifier's keyword match already confirmed relevance, and a
    # single-station query genuinely scores a weak distance on its own (see
    # RAG_DISTANCE_THRESHOLD above) without being off-topic.
    # The distance threshold was calibrated on English text with an English-only
    # embedding model; for Sinhala/Tamil it cannot tell on-topic from off-topic
    # (a legitimate Sinhala luggage question measured 1.87), so there the
    # railway-vocabulary check alone decides.
    off_topic = source_filter is None and (
        (language == "en" and chunks[0]["distance"] > RAG_DISTANCE_THRESHOLD)
        or (len(entity_stations) < 2 and not _mentions_railway(text, language))
    )
    if off_topic:
        # Not about this railway's passenger services: show the fixed system
        # notice. The LLM is not called at all, so it cannot answer from general
        # knowledge.
        print(f"[offtopic] intent={intent} query={text!r} top_distance={chunks[0]['distance']:.3f} -> out_of_scope notice")
        return OUT_OF_SCOPE_REPLIES.get(language, OUT_OF_SCOPE_REPLIES["en"]), ""

    sources = ", ".join(sorted({c["source"] for c in chunks}))

    # Bug fix: this used to be computed further down, only reachable once the
    # Gemini call actually succeeded - so the two raw-fallback returns below
    # (no gemini_model configured, or the API call itself failing - e.g. a
    # quota error) both bypassed it entirely and dumped the unmultiplied
    # per-person chunk text, even though passenger_count was already known.
    # Moved up so both fallback paths can use it too.
    passenger_count = (entities or {}).get("passenger_count")
    # Only meaningful for fare_query - narrows which fares.md line(s) are
    # relevant when the passenger named a class (e.g. "1st class", "AC").
    fare_class_keywords = (entities or {}).get("fare_class_keywords") or []

    # Fare-line extraction below must not mix in a different route's fares
    # that happened to also land in the top-k retrieval - fares.md has one
    # section per route, and a query only weakly favours the right one, so
    # e.g. a Colombo Fort-Badulla question can still retrieve the Kandy and
    # Anuradhapura sections too. Narrow to chunks whose text actually names
    # both stations when NER found a full route; fall back to every
    # retrieved chunk otherwise (e.g. a single-station "fare to Kandy").
    route_stations = (entities or {}).get("stations") or []
    if intent == "fare_query" and route_stations and not any(
        all(s.lower() in c["text"].lower() for s in route_stations) for c in chunks
    ):
        # Every named station must appear together in one fare section. If none
        # does, fares.md (== the booking system's table) has no fare for this
        # route - say so rather than quote a neighbouring route's price.
        print(f"[rag] no fare section covers stations={route_stations!r} -> fare not available")
        return FARE_NOT_AVAILABLE_REPLIES.get(language, FARE_NOT_AVAILABLE_REPLIES["en"]), ""
    if len(route_stations) >= 2:
        route_chunks = [
            c for c in chunks
            if all(s.lower() in c["text"].lower() for s in route_stations[:2])
        ]
        fare_chunks = route_chunks or chunks
    else:
        fare_chunks = chunks

    def _raw_fallback_text() -> str:
        localized = _localized_fallback_text(
            language, intent, chunks, fare_chunks, fare_class_keywords, passenger_count, route_stations
        )
        if localized is not None:
            return localized
        if intent == "fare_query" and fare_class_keywords:
            matched = _matching_fare_lines(fare_chunks, fare_class_keywords)
            requested = " ".join(fare_class_keywords)
            if matched:
                if passenger_count and passenger_count > 1:
                    computed = "\n".join(
                        f"- {label}: LKR {amt} x {passenger_count} passengers = LKR {amt * passenger_count}"
                        for label, amt in matched
                    )
                    return f"Here's what I found for {passenger_count} passengers:\n\n{computed}"
                computed = "\n".join(f"- {label}: LKR {amt} per person" for label, amt in matched)
                return f"Here's what I found:\n\n{computed}"
            return (
                f"I couldn't find a \"{requested}\" fare listed for this route. "
                f"Here's what is available:\n\n{_chunk_body(fare_chunks[0]['text'])}"
            )
        if intent == "fare_query" and passenger_count and passenger_count > 1:
            computed = _compute_group_fares(fare_chunks, passenger_count)
            if computed:
                return f"Here's what I found for {passenger_count} passengers:\n\n{computed}"
        return f"Here's what I found:\n\n{_chunk_body(chunks[0]['text'])}"

    if not gemini_model:
        print("[llm] SKIPPED - gemini_model is None (GEMINI_API_KEY missing/not loaded) - returning raw RAG chunk text")
        return _raw_fallback_text(), sources

    summary, recent_text = get_conversation_context(session_id)
    history_text = (
        (f"Summary of earlier conversation: {summary}\n\n" if summary else "")
        + (f"Recent messages:\n{recent_text}" if recent_text else "")
    ) or "(no prior messages)"
    # Only surface entities the NLU actually found - an empty/None-filled dict
    # would just add noise to the prompt instead of useful grounding signal.
    known_details = ", ".join(f"{k}={v}" for k, v in (entities or {}).items() if v) or "none extracted"

    # FIX 2: compute the group total in code rather than asking the LLM to
    # multiply - it isn't reliable at arithmetic. Only meaningful for
    # fare_query, and only when we actually know how many passengers.
    # (passenger_count itself is computed above, before the raw-fallback
    # returns, so it's available there too.)
    fare_block = ""
    if intent == "fare_query":
        if fare_class_keywords:
            # The passenger named a class - constrain the answer to just the
            # matching fares.md line(s) instead of every class on the route.
            matched = _matching_fare_lines(fare_chunks, fare_class_keywords)
            requested = " ".join(fare_class_keywords)
            if not matched:
                fare_block = (
                    f"FARE_CLASS_NOT_FOUND: true - the passenger specifically "
                    f'asked about a "{requested}" fare, but no such fare line '
                    f"exists for this route in the retrieved context below. Say "
                    f"that class isn't available for this route and list the "
                    f"class(es) that ARE, instead of guessing.\n\n"
                )
            else:
                lines_text = "\n".join(f"- {label}: LKR {amt}" for label, amt in matched)
                fare_block = (
                    f"FARE_CLASS_FILTER: true - the passenger specifically asked "
                    f'about a "{requested}" fare. Only report the matching fare '
                    f"line(s) below - do NOT mention any other class from the "
                    f"retrieved context even though it appears there too (kept "
                    f"only for route verification):\n{lines_text}\n\n"
                )
                if passenger_count and passenger_count > 1:
                    computed = "\n".join(
                        f"- {label}: LKR {amt} x {passenger_count} passengers = LKR {amt * passenger_count}"
                        for label, amt in matched
                    )
                    fare_block += (
                        f"Pre-computed total fares for {passenger_count} passengers "
                        f"(already multiplied in code - use these exact totals "
                        f"verbatim, do not recalculate them yourself):\n{computed}\n\n"
                    )
                elif not passenger_count:
                    fare_block += (
                        "PASSENGER_COUNT_UNKNOWN: true - state the per-person "
                        "fare(s) above clearly and ask how many passengers are "
                        "travelling before giving a total - do not assume 1 "
                        "passenger.\n\n"
                    )
        elif passenger_count and passenger_count > 1:
            computed = _compute_group_fares(fare_chunks, passenger_count)
            if computed:
                fare_block = (
                    f"Pre-computed total fares for {passenger_count} passengers "
                    f"(already multiplied in code - use these exact totals "
                    f"verbatim, do not recalculate them yourself):\n{computed}\n\n"
                )
        elif not passenger_count:
            fare_block = (
                "PASSENGER_COUNT_UNKNOWN: true - the passenger did not say how "
                "many people are travelling. State the per-person fare(s) "
                "clearly and ask how many passengers are travelling before "
                "giving a total - do not assume 1 passenger.\n\n"
            )

    context_text = "\n\n---\n\n".join(f"[{c['source']}] {c['text']}" for c in chunks)
    context_block = f"Retrieved knowledge base context:\n{context_text}\n\n"

    # FIX 4: an explicit imperative instruction, not just the `language:`
    # field below (which the system prompt also references) - makes the
    # language requirement something the model is directed to do on this
    # specific turn, not just background metadata it might deprioritize.
    prompt = (
        f"{_language_prompt_block(language)}\n\n"
        f"language: {language}\n\n"
        f"Detected intent: {intent}\n"
        f"Extracted details from the passenger's message: {known_details}\n\n"
        f"{fare_block}"
        f"Conversation history:\n{history_text}\n\n"
        f"{context_block}"
        f"Passenger's question: {text}"
    )

    print("[llm] LLM request started")
    try:
        response = gemini_model.generate_content(prompt)
        answer = (response.text or "").strip()
        print(f"[llm] Gemini response received ({len(answer)} chars)")
        if not answer:
            print("[llm] ERROR - Gemini returned an empty response - falling back")
            return _raw_fallback_text(), sources
        if language in _SCRIPT_RANGES and not _has_script(answer, language):
            # Not hidden and not "fixed" by translating: the answer is returned as
            # Gemini generated it, but the mismatch is visible in the logs.
            print(f"[llm] WARNING - reply for language={language} contains no {LANGUAGE_NAMES[language]} text")
        return answer, sources
    except Exception as e:
        print(f"[llm] ERROR - Gemini generation failed ({type(e).__name__}): {e} - falling back")
        return _raw_fallback_text(), sources


def touch_session(session_id: str, title_candidate: str | None = None):
    """Create the chat_sessions row on first message, or bump updated_at on later ones.

    No row is created until the first message actually sends (avoids empty-session
    clutter from a passenger opening "+ New chat" and never typing anything).
    """
    if _quick_chat.get():
        return  # Choo never creates a session row, so it never joins the sidebar list
    if not supabase:
        return
    try:
        existing = (
            supabase.table("chat_sessions")
            .select("session_id")
            .eq("session_id", session_id)
            .limit(1)
            .execute()
        )
        now = datetime.now(timezone.utc).isoformat()
        if existing.data:
            supabase.table("chat_sessions").update({"updated_at": now}).eq("session_id", session_id).execute()
        else:
            title = (title_candidate or "New conversation").strip()[:60] or "New conversation"
            supabase.table("chat_sessions").insert({
                "session_id": session_id,
                "title": title,
                "updated_at": now,
            }).execute()
    except Exception as e:
        print(f"Supabase session upsert failed: {e}")


def save_message(session_id: str, role: str, message: str):
    if _quick_chat.get():
        # In-process only, so the turn is still available for follow-up questions
        # in this visit but is never persisted anywhere.
        _quick_remember(session_id, role, message)
        return
    if not supabase:
        print("Warning: Supabase is not configured.")
        return

    touch_session(session_id, title_candidate=message if role == "user" else None)

    try:
        supabase.table("chat_messages").insert({
            "session_id": session_id,
            "role": role,
            "message": message,
        }).execute()
    except Exception as e:
        print(f"Supabase save failed: {e}")


def _extract_train_id(text: str) -> str:
    """Extract a canonical train ID from free text.

    Handles both registry conventions: prefixed ids (PM-4082, IC-4665) and the
    bare Sri Lanka Railways service numbers shown on the daily board (4085, 50,
    1005). The bare-number path reuses the NER extractor's guarded matcher so
    times, dates and passenger counts are never mistaken for a train id.
    """
    import re
    match = re.search(r"\b[A-Z]{2,12}-\d{3,5}\b", text, re.IGNORECASE)
    if match:
        return match.group(0).upper()
    from nlu.ner_extractor import _extract_bare_train_number
    return _extract_bare_train_number(text) or ""


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/trains/{train_id}/details")
def train_details(train_id: str):
    clean_id = train_id.strip().upper()
    # Accept both registry conventions: prefixed ids (PM-4082) and bare SLR
    # service numbers (4085, 50). The registry lookup below is the real
    # validation; this only rejects obviously malformed input.
    if not re.fullmatch(r"[A-Z]{2,12}-\d{3,5}|\d{1,4}", clean_id):
        raise HTTPException(status_code=404, detail="Train not found")
    try:
        details = get_train_details(clean_id)
    except TrainRepositoryUnavailable:
        raise HTTPException(status_code=503, detail="Train details are temporarily unavailable")
    if details is None:
        raise HTTPException(status_code=404, detail="Train not found")
    return {"train": details, "updated_at": datetime.now(timezone.utc).isoformat()}


OPERATIONS_AGENT_URL = os.getenv("OPERATIONS_AGENT_URL", "http://127.0.0.1:8005")
_m4_port = os.getenv("MAINTENANCE_AGENT_PORT", "8006")
MAINTENANCE_AGENT_URL = os.getenv("MAINTENANCE_AGENT_URL", f"http://127.0.0.1:{_m4_port}")
_OPERATIONS_INTENTS = {"delay_check", "train_status", "train_info", "schedule_query", "unknown"}


async def ask_operations_agent(text: str) -> dict | None:
    """M2's /passenger/query answer, or None when M2 declines or is unreachable."""
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(f"{OPERATIONS_AGENT_URL.rstrip('/')}/passenger/query",
                                     json={"question": text, "language": "en"})
        data = resp.json() if resp.status_code == 200 else {}
    except Exception as exc:
        print(f"[chat] operations agent unavailable: {exc!r}")
        return None
    if data.get("handled") and data.get("reply"):
        return data
    print(f"[chat] operations agent declined: {data.get('reason')}")
    return None


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    text = req.message.strip()
    print(f"[chat] received message={text!r} session_id={req.session_id}")

    language = detect_language(text)

    # FIX 1: short-circuits before intent classification/NER/RAG entirely -
    # a bare "hii" was previously falling through to classify_intent()'s
    # "unknown" fallback and then compose_rag_answer(), which had nothing
    # relevant to retrieve for it (see the off-topic guardrail below).
    if is_greeting(text):
        reply = GREETING_REPLIES.get(language, GREETING_REPLIES["en"])
        print(f"[chat] greeting short-circuit language={language}")
        save_message(req.session_id, "user", text)
        save_message(req.session_id, "assistant", reply)
        return ChatResponse(
            session_id=req.session_id, reply=reply, intent="greeting",
            language=language, entities={}, source="local",
        )

    intent = classify_intent(text)
    entities = extract_entities(text)
    if entities.get("train_id") and intent == "schedule_query":
        intent = "train_info"
    print(f"[chat] language={language} intent={intent}")

    # Train operations questions (live position, delays, "any train to X after
    # 19:15?", station ETAs, incidents) are answered by the Operations Agent
    # (M2) from the real timetable, live journey and verified incidents. M2
    # returns handled=false for anything else, which then continues below.
    if language == "en" and intent in _OPERATIONS_INTENTS:
        ops = await ask_operations_agent(text)
        if ops:
            # M4 maintenance flags override M2's operational data for delay/status intents.
            # A train flagged by an engineer is not in service regardless of the schedule.
            _m4_train_id = entities.get("train_id")
            if _m4_train_id and intent in ("delay_check", "train_status"):
                try:
                    async with httpx.AsyncClient(timeout=8) as _m4_client:
                        _m4_resp = await _m4_client.get(
                            f"{MAINTENANCE_AGENT_URL.rstrip('/')}/api/train-status/{_m4_train_id}"
                        )
                    if _m4_resp.status_code == 200:
                        _mp = _m4_resp.json()
                        if _mp.get("under_maintenance") and _mp.get("found") is not False:
                            try:
                                _tr_row = await asyncio.to_thread(get_train, _m4_train_id)
                                _train_name = (_tr_row or {}).get("train_name") or _m4_train_id
                            except Exception:
                                _train_name = _m4_train_id
                            _reason = _mp.get("reason", "Technical issue under investigation")
                            _delay_mins = _mp.get("delay_minutes")
                            _eta = _mp.get("estimated_clear")
                            _maint_str = t("delay_maint", language, reason=_reason)
                            _delay_str = f" Expected delay: {_delay_mins} minutes." if _delay_mins is not None else ""
                            _eta_str = t("delay_maint_eta", language, eta=_eta) if _eta else ""
                            _maint_reply = f"{_train_name} is currently under maintenance. {_maint_str}{_delay_str}{_eta_str}"
                            save_message(req.session_id, "user", text)
                            save_message(req.session_id, "assistant", _maint_reply)
                            return ChatResponse(
                                session_id=req.session_id, reply=_maint_reply, intent=intent,
                                language=language, entities=entities,
                                source="via Maintenance Agent (Hub)",
                            )
                except Exception:
                    pass  # M4 unreachable — return M2's answer unchanged
            save_message(req.session_id, "user", text)
            save_message(req.session_id, "assistant", ops["reply"])
            return ChatResponse(
                session_id=req.session_id, reply=ops["reply"], intent=intent,
                language=language,
                entities={**entities, "operations": {"intent": ops.get("intent"), "kind": ops.get("kind"),
                                                     **(ops.get("entities") or {})}},
                source="via Operations Agent (M2)",
            )

    source = "local"
    reply = ""
    delay_minutes = None
    action = None
    prefill = None
    cancellation = None

    if intent in ("schedule_query", "fare_query", "policy_query"):
        reply, source = compose_rag_answer(
            text, language, req.session_id,
            source_filter=INTENT_SOURCE_DOC[intent], intent=intent, entities=entities,
        )

    elif intent == "engineering_query":
        # Engineer-facing manuals stay behind the Maintenance Agent. No Hub call
        # and no retrieval - the passenger just gets the fixed notice.
        reply = ENGINEERING_NOTICE_REPLIES.get(language, ENGINEERING_NOTICE_REPLIES["en"])
        source = ""

    elif intent == "train_info":
        train_id = entities.get("train_id")
        if not train_id:
            reply = t("train_id_needed_info", language)
            source = "via Shared Train Registry"
        else:
            try:
                train = await asyncio.to_thread(get_train, train_id)
                if train is None:
                    # "TRAIN_NOT_FOUND:" is a cross-team sentinel - kept as the prefix
                    # in every language; the sentence after it is localized.
                    reply = f"TRAIN_NOT_FOUND: {t('train_not_found_registry', language, train_id=train_id)}"
                else:
                    schedules = await asyncio.to_thread(get_train_schedule, train_id)
                    route = train.get("route") or t("route_not_recorded", language)
                    state = t("train_state_active" if train.get("active") else "train_state_inactive", language)
                    name = train.get("train_name") or train_id
                    maintenance = train.get("maintenance_status", "UNKNOWN")
                    first = schedules[0] if schedules else None
                    next_service = (
                        t("train_next_service", language,
                          origin=_disp(first.get("from_station"), language),
                          destination=_disp(first.get("to_station"), language),
                          date=first.get("travel_date"), time=first.get("departure_time"))
                        if first else ""
                    )
                    template = t("train_info_main", language, name=name, train_id=train_id, state=state,
                                 route=route, maintenance=maintenance) + next_service
                    presented = await asyncio.to_thread(
                        present_agent_result, language, text, "train registry record",
                        {"train_name": name, "train_id": train_id, "status": state, "route": route,
                         "maintenance_status": maintenance,
                         "next_recorded_service": next_service.strip() or None},
                        [train_id],
                    )
                    reply = presented or template
                source = "via Shared Train Registry"
            except TrainRepositoryUnavailable:
                reply = t("registry_unavailable", language)
                source = "via Shared Train Registry"

    elif intent == "delay_check":
        stations = entities.get("stations", [])
        if entities.get("from_station") and entities.get("to_station"):
            # spoken direction (e.g. "Kandy to Colombo"), not dictionary order
            stations = [entities["from_station"], entities["to_station"]]
        # No invented default here. This used to fall back to "Colombo Fort -
        # Kandy", so every "Is <train> delayed?" that named no stations was
        # answered for the Kandy line - wrong for PM-8056 (Badulla), 1005
        # (Colombo - Badulla) and most of the board. When the passenger names
        # no stations we send no route, and Operations fills it in from the
        # shared registry entry for the train they did name.
        route = " - ".join(stations) if isinstance(stations, list) and len(stations) >= 2 else None
        train_id = entities.get("train_id")
        resolved_via_registry = False
        # If train_id was resolved from a name ("Intercity Express" → "T-002")
        # rather than typed explicitly, it won't appear in the passenger's text.
        # Mark it as resolved so raw_text_for_hub gets "(train T-002)" appended,
        # satisfying M2's anti-fabrication guard.
        import re as _re
        if train_id and not _re.search(rf'(?<![A-Za-z0-9]){_re.escape(train_id)}(?![A-Za-z0-9])', text, _re.IGNORECASE):
            resolved_via_registry = True
        if not train_id and isinstance(stations, list) and len(stations) >= 2:
            # No explicit train ID (e.g. "Is the train from Colombo Fort to
            # Kandy delayed?"), but a route is known - M2's PredictionRequest
            # requires a train_id (Field(..., ...), no default), so this
            # can't just be omitted from the Hub call. Look up a real train
            # on that route via the shared registry instead of forcing the
            # passenger to already know a specific train ID.
            try:
                matches = await asyncio.to_thread(search_trains, stations[0], stations[1])
                if matches:
                    train_id = matches[0]["train_id"]
                    resolved_via_registry = True
                    print(f"[chat] delay_check resolved train_id={train_id!r} for route={route!r} via shared registry")
            except TrainRepositoryUnavailable as e:
                print(f"[chat] delay_check registry lookup failed for route={route!r}: {e}")
                # Registry unavailable (no Supabase creds) — use a route-derived
                # fallback so mock mode and Hub calls can still be exercised.
                if USE_MOCK_HUB:
                    train_id = f"ROUTE-{stations[0][:3].upper()}-{stations[1][:3].upper()}"
                    resolved_via_registry = True
                    print(f"[chat] delay_check using fallback train_id={train_id!r} (mock mode, registry down)")
        if not train_id:
            reply = f"TRAIN_NOT_FOUND: {t('delay_need_train_id', language)}"
            source = "via Operations Agent (Hub)"
            save_message(req.session_id, "user", text)
            save_message(req.session_id, "assistant", reply)
            return ChatResponse(session_id=req.session_id, reply=reply, intent=intent, language=language, entities=entities, source=source)

        # ── M4 maintenance fast-path ──────────────────────────────────────────
        # Check M4 before M2. If the engineer has flagged this train, the
        # maintenance record is authoritative — no need to call M2 at all.
        try:
            maint_env = build_envelope(
                receiver_agent="maintenance-agent",
                intent="train_status_query",
                payload={"train_id": train_id, "raw_text": text, "language": language},
            )
            maint_resp = await send_to_hub(maint_env)
            if maint_resp.status == "ok":
                mp = maint_resp.payload
                if mp.get("under_maintenance"):
                    reason_text = mp.get("reason", "Technical issue under investigation")
                    delay_mins  = mp.get("delay_minutes")
                    eta         = mp.get("estimated_clear")
                    try:
                        tr_row = await asyncio.to_thread(get_train, train_id)
                        train_name = (tr_row or {}).get("train_name") or train_id
                    except Exception:
                        train_name = train_id
                    maint_str = t("delay_maint", language, reason=reason_text)
                    delay_str = f" Expected delay: {delay_mins} minutes." if delay_mins is not None else ""
                    eta_str   = t("delay_maint_eta", language, eta=eta) if eta else ""
                    reply  = f"{train_name} is currently under maintenance. {maint_str}{delay_str}{eta_str}"
                    source = "via Maintenance Agent (Hub)"
                    save_message(req.session_id, "user", text)
                    save_message(req.session_id, "assistant", reply)
                    return ChatResponse(session_id=req.session_id, reply=reply, intent=intent, language=language, entities=entities, source=source)
        except Exception:
            pass  # M4 unreachable — fall through to M2

        # Operations' own /hub/message contract (M2, unmodified) only trusts a
        # payload train_id when it's also evidenced by a matching token in
        # raw_text - an anti-fabrication guard against a caller defaulting to
        # a placeholder ID with no real basis. When we resolved train_id
        # ourselves via the shared registry rather than the passenger naming
        # one, the verbatim chat text won't contain it, so surface it as
        # explicit evidence here rather than touching M2's validation.
        raw_text_for_hub = f"{text} (train {train_id})" if resolved_via_registry else text
        envelope = build_envelope(
            receiver_agent="operations-agent",
            intent="delay_check",
            payload={
                "stations": stations,
                "time": entities.get("time"),
                "raw_text": raw_text_for_hub,
                "route": route,
                "train_id": train_id,
                "language": language,  # passenger's language - agents can keep/echo it; M1 writes the final reply in it
            },
        )
        hub_response = await send_to_hub(envelope)
        if hub_response.status == "ok":
            p = hub_response.payload
            # Operations' /hub/message hands back structured fields, not one
            # composed sentence (unlike Maintenance/Booking below) - this
            # assembles them, it doesn't re-run anything through an LLM.
            # Operations resolved the identity against the shared registry, so
            # its values win: "4082" comes back as PM-4082, and the route it
            # priced the prediction on is the one the reply must quote.
            train_id = p.get("train_id") or train_id
            route = p.get("route") or route
            delay = p.get("predicted_delay_minutes", 0)
            delay_minutes = float(delay)
            reason = p.get("reason") or p.get("explanation", "Operational congestion")
            similar = p.get("similar_incident")
            if not similar and p.get("similar_past_incidents"):
                similar = p["similar_past_incidents"][0]
            if not similar:
                similar = "No similar historical incident recorded"

            # Always query M4 for live maintenance status — if the engineer
            # flagged this train, the passenger gets the real reason and delay,
            # not just M2's statistical prediction.
            maintenance_context = ""
            if train_id:
                try:
                    maint_envelope = build_envelope(
                        receiver_agent="maintenance-agent",
                        intent="train_status_query",
                        payload={"train_id": train_id, "raw_text": text, "language": language},
                    )
                    maint_response = await send_to_hub(maint_envelope)
                    if maint_response.status == "ok":
                        mp = maint_response.payload
                        if mp.get("under_maintenance"):
                            # M4's engineer-set delay overrides M2's prediction
                            if mp.get("delay_minutes") is not None:
                                delay_minutes = float(mp["delay_minutes"])
                                delay = delay_minutes
                            maintenance_context = " " + t(
                                "delay_maint", language,
                                reason=mp.get("reason", "Technical issue under investigation"),
                            ) + (
                                t("delay_maint_eta", language, eta=mp["estimated_clear"])
                                if mp.get("estimated_clear")
                                else ""
                            )
                except Exception:
                    pass

            # M2 answers from its 2025 incident history. When it matched a
            # recorded observation for this exact train
            # (retrieval_method="historical_record"), the number is a past
            # record, not a live reading - say so, and keep "similar past
            # incident" labelled as history rather than current status.
            is_historical = (
                p.get("retrieval_method") == "historical_record"
                or str(p.get("model_version", "")).startswith("historical-observation")
            )
            reason_text = str(reason).strip().rstrip(".")
            similar_text = str(similar).rstrip(".")
            headline = t("delay_headline_hist" if is_historical else "delay_headline_est", language, delay=delay)
            if language != "en":
                # Deterministic Sinhala/Tamil fallback (Gemini unavailable/rejected): only the
                # structured facts - the delay figure and whether it is history or an estimate.
                # Operations' explanation and incident notes are free-form English sentences that
                # cannot be translated without the LLM, so they are left out rather than pasted
                # into a Sinhala/Tamil reply.
                template = headline + (f" {t('delay_maint_note', language)}" if maintenance_context else "")
            elif is_historical:
                template = f"{headline} {t('delay_record', language, reason=reason_text)}{maintenance_context}"
            else:
                template = (
                    f"{headline} {t('delay_reason', language, reason=reason_text)}{maintenance_context} "
                    f"{t('delay_similar', language, similar=similar_text)}"
                )
            # Sinhala/Tamil: Gemini writes the answer from the Operations result
            # (guarded: the delay figure and train ID must appear verbatim, else the
            # localized template above is used). English keeps the template.
            presented = await asyncio.to_thread(
                present_agent_result, language, text, "Operations delay result",
                {
                    "train_id": train_id, "route": route,
                    "delay_minutes": delay,
                    "basis": (
                        "a recorded past observation for this exact train - NOT a live status"
                        if is_historical else "a model estimate - NOT a live status"
                    ),
                    "operations_explanation": reason_text,
                    "similar_past_incident_historical": None if is_historical else similar_text,
                    "live_maintenance_update": maintenance_context.strip() or None,
                },
                [str(abs(delay_minutes)).rstrip("0").rstrip(".") or "0", train_id],
            )
            reply = presented or template
            source = "via Operations Agent + Maintenance Agent (Hub)" if maintenance_context else "via Operations Agent (Hub)"
        else:
            fallback = (
                _agent_error(language, hub_response)
                if getattr(hub_response, "error_kind", None) == "rejected"
                else DELAY_UNREACHABLE_REPLIES.get(language, DELAY_UNREACHABLE_REPLIES["en"])
            )
            message = hub_response.message or fallback
            # TRAIN_NOT_FOUND is a cross-team sentinel M2 also emits - kept as the
            # prefix (something downstream may match on it); in Sinhala/Tamil the
            # sentence after it is localized instead of passing English through.
            if "TRAIN_NOT_FOUND" in message:
                reply = message if language == "en" else f"TRAIN_NOT_FOUND: {t('delay_need_train_id', language)}"
            else:
                reply = fallback
            source = "via Operations Agent (Hub)"

    elif intent == "train_status":
        train_id = entities.get("train_id") or _extract_train_id(text)
        if not train_id:
            reply = t("train_id_needed_status", language)
            source = "local"
        else:
            try:
                canonical = await asyncio.to_thread(get_train, train_id)
                if canonical is None:
                    reply = f"TRAIN_NOT_FOUND: {t('train_not_found_status', language, train_id=train_id)}"
                    source = "via Shared Train Registry"
                else:
                    envelope = build_envelope(
                        receiver_agent="maintenance-agent",
                        intent="train_status_query",
                        payload={"train_id": train_id, "raw_text": text, "language": language},
                    )
                    hub_response = await send_to_hub(envelope)
                    if hub_response.status == "ok":
                        p = hub_response.payload
                        if language == "en":
                            reply = p.get("message") or t("train_status_failed", language)
                        else:
                            # Maintenance's own text is English; write the answer in the
                            # passenger's language from its structured fields (Gemini, with a
                            # deterministic localized template as the guarded fallback).
                            if p.get("under_maintenance"):
                                eta = p.get("estimated_clear")
                                template = t("train_status_maint", language, train_id=train_id,
                                             reason=p.get("reason", ""),
                                             eta=t("train_status_eta", language, eta=eta) if eta else "")
                            elif p.get("found") or p.get("train_id"):
                                template = t("train_status_clear", language, train_id=train_id)
                            else:
                                template = t("train_status_failed", language)
                            presented = await asyncio.to_thread(
                                present_agent_result, language, text, "Maintenance train status",
                                {"train_id": train_id, "under_maintenance": p.get("under_maintenance"),
                                 "maintenance_reason": p.get("reason"),
                                 "estimated_back_in_service": p.get("estimated_clear"),
                                 "agent_message_english": p.get("message")},
                                [train_id],
                            )
                            reply = presented or template
                    else:
                        reply = t("train_status_failed", language)
                    source = "via Maintenance Agent"
            except TrainRepositoryUnavailable:
                reply = t("registry_unavailable", language)
                source = "via Shared Train Registry"

    elif intent == "complaint":
        stations = entities.get("stations", [])
        station = entities.get("station") or (stations[0] if stations else "")
        envelope = build_envelope(
            receiver_agent="maintenance-agent",
            intent="issue_report",
            payload={
                "description": text,
                "train_id": entities.get("train_id", ""),
                "station": station,
                "language": language,  # passenger's language travels with the report
            },
        )
        hub_response = await send_to_hub(envelope)
        if hub_response.status == "ok":
            p = hub_response.payload
            ticket = p.get("ticket_id", "-")
            if language == "en":
                # English: Maintenance's own text passed through, plus the ticket id.
                reply = f"{p.get('message', '')} (Ticket: {ticket})".strip()
            else:
                presented = await asyncio.to_thread(
                    present_agent_result, language, text, "Maintenance issue ticket",
                    {"ticket_reference": ticket, "agent_message_english": p.get("message"),
                     "passenger_report": text},
                    [ticket],
                )
                reply = presented or t("complaint_logged", language, ticket=ticket)
            source = "via Maintenance Agent"
        else:
            reply = (
                t("complaint_failed", language) if getattr(hub_response, "error_kind", None) == "rejected"
                else _agent_error(language, hub_response)
            )
            source = "via Maintenance Agent"

    elif intent == "booking_request":
        from_st = entities.get("from_station")
        to_st = entities.get("to_station")
        t_date = entities.get("travel_date")
        prefill = {
            key: value
            for key, value in {
                "from_station": from_st,
                "to_station": to_st,
                "travel_date": t_date,
                "train_id": entities.get("train_id"),
                "seat_class": entities.get("seat_class"),
                "passenger_count": entities.get("passenger_count"),
            }.items()
            if value not in (None, "")
        }
        query_values = {
            "from": prefill.get("from_station"),
            "to": prefill.get("to_station"),
            "date": prefill.get("travel_date"),
            "train_id": prefill.get("train_id"),
            "seat_class": prefill.get("seat_class"),
            "passenger_count": prefill.get("passenger_count"),
        }
        query_str = urlencode({key: value for key, value in query_values.items() if value not in (None, "")})
        query_str = f"?{query_str}" if query_str else ""
        booking_url = f"http://localhost:3000/user/booking{query_str}"

        action = {
            "type": "continue_to_booking",
            "label": t("label_continue_booking", language),
            "url": booking_url,
            "prefill": prefill,
        }

        if not (from_st and to_st):
            # A required station is missing: ask for it in the passenger's language.
            # The station that WAS named keeps its own role (a destination is never
            # turned into an origin) and the missing one is never guessed. The card
            # above stays so the passenger can also finish in the booking desk.
            if to_st:
                reply = t("booking_ask_origin", language, destination=_disp(to_st, language))
            elif from_st:
                reply = t("booking_ask_destination", language, origin=_disp(from_st, language))
            else:
                reply = t("booking_ask_both", language)
            source = "local"
        else:
            date_part = t("booking_date_part", language, date=t_date) if t_date else ""
            reply = t("booking_found", language, origin=_disp(from_st, language),
                      destination=_disp(to_st, language), date_part=date_part)
            source = "Passenger Assistant booking link"
    elif intent == "cancel_booking":
        booking_ref = entities.get("booking_reference") or _extract_train_id(text)
        reason = entities.get("reason") or "No reason provided"  # API value sent to the Booking Agent
        reason_shown = entities.get("reason") or t("no_reason_provided", language)
        reply = (
            t("cancel_prepared", language, ref=booking_ref, reason=reason_shown)
            if booking_ref
            else t("cancel_need_ref", language, reason=reason_shown)
        )
        cancellation = {
            "booking_reference": booking_ref or "",
            "reason": reason,
        }
        action = {
            "type": "cancellation_confirmation_card",
            "label": t("label_send_cancellation", language),
            "booking_reference": booking_ref or "",
            "reason": reason,
        }
        source = "via Booking Agent (Hub)"

    else:
        # Natural route questions can miss the keyword classifier. Resolve them
        # against the shared registry before falling back to FAQ retrieval.
        route_words = text.lower()
        mentions_train = "train" in route_words or "දුම්රිය" in text or "ரயில்" in text
        if len(entities.get("stations", [])) >= 2 and mentions_train:
            origin, destination = (
                (entities["from_station"], entities["to_station"])
                if entities.get("from_station") and entities.get("to_station")
                else entities["stations"][:2]
            )
            try:
                services = await asyncio.to_thread(search_trains, origin, destination)
                if services:
                    service_lines = [
                        f"{service.get('train_id') or 'N/A'} — {service.get('train_name') or 'N/A'}"
                        for service in services[:10]
                    ]
                    reply = (
                        t("route_found", language, n=len(services),
                          origin=_disp(origin, language), destination=_disp(destination, language))
                        + "\n" + "\n".join(f"- {line}" for line in service_lines)
                    )
                    source = "via Shared Train Registry"
                else:
                    reply = t("route_none", language, origin=_disp(origin, language), destination=_disp(destination, language))
                    source = "via Shared Train Registry"
            except TrainRepositoryUnavailable:
                reply = t("registry_unavailable", language)
                source = "via Shared Train Registry"
        else:
            # Keyword classifier missed this one - try the FAQ docs before giving up.
            # compose_rag_answer() already returns a clear "not found, try rephrasing"
            # message (with source="") when nothing relevant is retrieved.
            reply, source = compose_rag_answer(text, language, req.session_id, intent=intent, entities=entities)
            if reply in OUT_OF_SCOPE_REPLIES.values():
                intent = "out_of_scope"  # lets the UI show it as a service notice

    save_message(req.session_id, "user", text)
    save_message(req.session_id, "assistant", reply)

    print(f"[chat] final answer source={source!r} reply={reply[:120]!r}")
    return ChatResponse(
        session_id=req.session_id,
        reply=reply,
        intent=intent,
        language=language,
        entities=entities,
        source=source,
        delay_minutes=delay_minutes,
        action=action,
        prefill=prefill,
        cancellation=cancellation,
    )


@app.post("/chat/quick", response_model=ChatResponse)
async def chat_quick(req: ChatRequest):
    """Same answers as /chat, with nothing written to the database.

    This is what the Choo widget on the passenger pages calls. The whole
    pipeline runs unchanged - language detection, intent, NER, RAG retrieval,
    the Hub agents (M2/M4), the shared train registry and the LLM - so a
    question answered here gets the same grounded, LLM-composed reply the full
    Passenger Assistant gives. What it skips is persistence: no chat_sessions,
    chat_messages or chat_summaries row is written, so a quick question never
    appears in the sidebar (GET /chat) or in GET /chat/{session_id}/history.

    Follow-up questions still work while the visitor keeps the panel open - the
    last few turns are held in memory (see _quick_messages) and expire on their
    own.
    """
    validate_session_id(req.session_id)
    token = _quick_chat.set(True)
    try:
        return await chat(req)
    finally:
        _quick_chat.reset(token)


@app.get("/chat/{session_id}/history")
def history(session_id: str):
    validate_session_id(session_id)
    if not supabase:
        return {"session_id": session_id, "messages": [], "error": "Supabase is not configured"}

    try:
        result = (
            supabase
            .table("chat_messages")
            .select("*")
            .eq("session_id", session_id)
            .order("created_at")
            .execute()
        )
        return {"session_id": session_id, "messages": result.data}
    except Exception as e:
        print(f"Supabase history failed: {e}")
        return {"session_id": session_id, "messages": [], "error": str(e)}


@app.get("/chat", response_model=list[SessionSummary])
def list_sessions():
    """Sidebar chat list: pinned sessions first, then most-recently-active."""
    if not supabase:
        return []
    try:
        result = (
            supabase.table("chat_sessions")
            .select("*")
            .order("is_pinned", desc=True)
            .order("updated_at", desc=True)
            .execute()
        )
        return result.data
    except Exception as e:
        print(f"Supabase session list failed: {e}")
        return []


def get_session_or_404(session_id: str):
    """Look up a chat_sessions row, or raise a clean HTTP error.

    Wraps the query itself (not just the later mutation) - if the chat_sessions
    table hasn't been created yet (see supabase_schema.sql), Supabase raises on
    the SELECT itself, which would otherwise surface as an opaque 500 instead
    of a message that tells the caller what to actually go fix.
    """
    try:
        existing = (
            supabase.table("chat_sessions").select("session_id").eq("session_id", session_id).limit(1).execute()
        )
    except Exception as e:
        print(f"Supabase session lookup failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="Chat storage isn't set up yet - run backend/supabase_schema.sql against this Supabase project.",
        )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Session not found")


@app.delete("/chat/{session_id}", status_code=204)
def delete_chat(session_id: str):
    validate_session_id(session_id)
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase is not configured")

    get_session_or_404(session_id)

    try:
        # Explicit two-step hard delete rather than relying on the FK's ON
        # DELETE CASCADE - keeps this correct even on a database where that
        # constraint didn't attach cleanly (see supabase_schema.sql).
        supabase.table("chat_messages").delete().eq("session_id", session_id).execute()
        _session_summaries.pop(session_id, None)
        try:
            supabase.table("chat_summaries").delete().eq("session_id", session_id).execute()
        except Exception as e:
            print(f"[context] summary delete failed: {e}")
        supabase.table("chat_sessions").delete().eq("session_id", session_id).execute()
    except Exception as e:
        print(f"Supabase delete failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete session")
    return None


@app.patch("/chat/{session_id}/title", response_model=SessionSummary)
def rename_chat(session_id: str, req: TitleRequest):
    validate_session_id(session_id)
    title = req.title.strip()[:80]
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    get_session_or_404(session_id)

    try:
        result = (
            supabase.table("chat_sessions")
            .update({"title": title})
            .eq("session_id", session_id)
            .execute()
        )
        return result.data[0]
    except Exception as e:
        print(f"Supabase rename failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to rename session")


@app.patch("/chat/{session_id}/pin", response_model=SessionSummary)
def pin_chat(session_id: str, req: PinRequest):
    validate_session_id(session_id)
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase is not configured")

    get_session_or_404(session_id)

    try:
        result = (
            supabase.table("chat_sessions")
            .update({"is_pinned": req.pinned, "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("session_id", session_id)
            .execute()
        )
        return result.data[0]
    except Exception as e:
        print(f"Supabase pin update failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to update session")


@app.post("/feedback")
def feedback(req: FeedbackRequest):
    if not supabase:
        return {"status": "received", "session_id": req.session_id, "saved": False}

    try:
        supabase.table("feedback").insert({
            "session_id": req.session_id,
            "rating": req.rating,
            "comment": req.comment,
        }).execute()
        return {"status": "received", "session_id": req.session_id, "saved": True}
    except Exception as e:
        print(f"Supabase feedback failed: {e}")
        return {"status": "received", "session_id": req.session_id, "saved": False, "error": str(e)}


# Mount pre-built React/Vite UI if available
from fastapi.staticfiles import StaticFiles
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.exists() and (_frontend_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
