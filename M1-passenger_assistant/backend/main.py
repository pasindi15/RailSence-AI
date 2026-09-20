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
import uuid
import asyncio
from pathlib import Path
from datetime import datetime, timezone

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

try:
    # pyrefly: ignore [missing-import]
    import google.generativeai as genai
except ImportError:
    genai = None
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client

from nlu.lang_detect import detect_language
from nlu.intent_classifier import classify_intent, is_greeting
from nlu.ner_extractor import extract_entities
from hub_client import build_envelope, send_to_hub
from rag.retriever import retrieve_faq_chunks
from shared.train_repository import TrainRepositoryUnavailable, get_train, get_train_details, get_train_schedule, search_trains

# load_dotenv() with no path searches upward from the CWD, not from this
# file's location - if uvicorn is ever launched from outside backend/, that
# silently finds no .env, GEMINI_API_KEY stays None, and /chat falls back to
# raw RAG chunk text with zero errors. Anchor it to this file instead.
load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system_prompt.md").read_text(encoding="utf-8")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini_model = None
if GEMINI_API_KEY and genai is not None:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-flash-latest", system_instruction=SYSTEM_PROMPT)
    print(f"[startup] GEMINI_API_KEY loaded (len={len(GEMINI_API_KEY)}) - Gemini model ready: gemini-flash-latest")
else:
    print("[startup] WARNING: GEMINI_API_KEY not set - /chat will fall back to raw RAG chunk text, not LLM answers")

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


# Matches crypto.randomUUID() from the frontend (and str(uuid.uuid4()) from the
# ChatRequest default). Rejecting anything else before it reaches a Supabase
# filter keeps session_id out of query-building entirely, not just escaped.
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def validate_session_id(session_id: str) -> None:
    if not SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")


def get_recent_history(session_id: str, turns: int = 3) -> list[dict]:
    """Last `turns` conversation turns (user+assistant pairs) for this session, oldest first."""
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


# fare_query / schedule_query map 1:1 to a doc, so retrieval can skip
# straight to it instead of relying on embedding similarity to pick the
# right file (e.g. "train fare" otherwise ranks schedules.md over fares.md).
INTENT_SOURCE_DOC = {
    "fare_query": "fares.md",
    "schedule_query": "schedules.md",
}

LANGUAGE_NAMES = {"si": "Sinhala", "ta": "Tamil", "en": "English"}

# Fixed, non-LLM replies for FIX 1 (greetings) - deliberately not a Gemini
# call, so this stays instant and free even under load. Written per-language
# rather than relying on translation at request time, matching FIX 4's "no
# English fallback" requirement for the small set of canned reply paths.
GREETING_REPLIES = {
    "en": "Hi! I'm the Sri Lanka Railways assistant — I can help with schedules, fares, delays, or booking. What do you need?",
    "si": "ආයුබෝවන්! මම ශ්‍රී ලංකා දුම්රිය සහායකයා — කාලසටහන්, ගාස්තු, ප්‍රමාදවීම් හෝ වෙන්කිරීම් සම්බන්ධයෙන් මට ඔබට උදව් කළ හැක. ඔබට අවශ්‍ය කුමක්ද?",
    "ta": "வணக்கம்! நான் இலங்கை ரயில்வே உதவியாளர் — அட்டவணைகள், கட்டணங்கள், தாமதங்கள் அல்லது முன்பதிவு குறித்து உங்களுக்கு உதவ முடியும். உங்களுக்கு என்ன தேவை?",
}

# Only used when gemini_model isn't configured at all (FIX 3's LLM-guided
# decline path below covers the normal case) - still needs to be in-language
# per FIX 4 rather than a hardcoded English string.
OFF_TOPIC_FALLBACK = {
    "en": "I can only help with railway schedules, fares, delays, or complaints — is there something about your journey I can help with?",
    "si": "මට උදව් කළ හැක්කේ දුම්රිය කාලසටහන්, ගාස්තු, ප්‍රමාදවීම් හෝ පැමිණිලි සම්බන්ධයෙන් පමණි — ඔබේ ගමන සම්බන්ධයෙන් මට උදව් කළ හැකි දෙයක් තිබේද?",
    "ta": "நான் ரயில் அட்டவணைகள், கட்டணங்கள், தாமதங்கள் அல்லது புகார்கள் தொடர்பாக மட்டுமே உதவ முடியும் — உங்கள் பயணம் தொடர்பாக நான் உதவக்கூடிய ஏதாவது உள்ளதா?",
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
        return "I'm having trouble looking that up right now. Please try again in a moment.", ""
    print(f"[rag] retrieved {len(chunks)} chunk(s) for query={retrieval_query!r} (original text={text!r}) source_filter={source_filter!r}")
    if not chunks:
        print(f"[offtopic] intent={intent} query={text!r} reason=no_chunks_retrieved")
        return (
            "I don't have that information in my current knowledge base. "
            "Could you rephrase, or ask about schedules, fares, delays, or bookings instead?"
        ), ""

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
    off_topic = source_filter is None and chunks[0]["distance"] > RAG_DISTANCE_THRESHOLD
    if off_topic:
        print(f"[offtopic] intent={intent} query={text!r} top_distance={chunks[0]['distance']:.3f}")

    sources = "" if off_topic else ", ".join(sorted({c["source"] for c in chunks}))

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
    if len(route_stations) >= 2:
        route_chunks = [
            c for c in chunks
            if all(s.lower() in c["text"].lower() for s in route_stations[:2])
        ]
        fare_chunks = route_chunks or chunks
    else:
        fare_chunks = chunks

    def _raw_fallback_text() -> str:
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
                f"Here's what is available:\n\n{fare_chunks[0]['text'][:400]}"
            )
        if intent == "fare_query" and passenger_count and passenger_count > 1:
            computed = _compute_group_fares(fare_chunks, passenger_count)
            if computed:
                return f"Here's what I found for {passenger_count} passengers:\n\n{computed}"
        return f"Here's what I found:\n\n{chunks[0]['text'][:400]}"

    if not gemini_model:
        if off_topic:
            return OFF_TOPIC_FALLBACK.get(language, OFF_TOPIC_FALLBACK["en"]), ""
        print("[llm] SKIPPED - gemini_model is None (GEMINI_API_KEY missing/not loaded) - returning raw RAG chunk text")
        return _raw_fallback_text(), sources

    history = get_recent_history(session_id)
    history_text = "\n".join(f"{h['role']}: {h['message']}" for h in history) or "(no prior messages)"
    # Only surface entities the NLU actually found - an empty/None-filled dict
    # would just add noise to the prompt instead of useful grounding signal.
    known_details = ", ".join(f"{k}={v}" for k, v in (entities or {}).items() if v) or "none extracted"

    # FIX 2: compute the group total in code rather than asking the LLM to
    # multiply - it isn't reliable at arithmetic. Only meaningful for
    # fare_query, and only when we actually know how many passengers.
    # (passenger_count itself is computed above, before the raw-fallback
    # returns, so it's available there too.)
    fare_block = ""
    if intent == "fare_query" and not off_topic:
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

    if off_topic:
        context_block = (
            "OFF_TOPIC: true - the retrieved knowledge base has no relevant "
            "railway information for this question. Politely decline and "
            "redirect the passenger to what you can help with instead. Do "
            "not attempt to answer using your own general knowledge, even if "
            "you know the answer.\n\n"
        )
    else:
        context_text = "\n\n---\n\n".join(f"[{c['source']}] {c['text']}" for c in chunks)
        context_block = f"Retrieved knowledge base context:\n{context_text}\n\n"

    # FIX 4: an explicit imperative instruction, not just the `language:`
    # field below (which the system prompt also references) - makes the
    # language requirement something the model is directed to do on this
    # specific turn, not just background metadata it might deprioritize.
    language_instruction = f"Respond only in {LANGUAGE_NAMES.get(language, 'English')}."

    prompt = (
        f"{language_instruction}\n\n"
        f"language: {language}\n\n"
        f"Detected intent: {intent}\n"
        f"Extracted details from the passenger's message: {known_details}\n\n"
        f"{fare_block}"
        f"Conversation history:\n{history_text}\n\n"
        f"{context_block}"
        f"Passenger's question: {text}"
    )

    print("[llm] Gemini request started (gemini-flash-latest)")
    try:
        response = gemini_model.generate_content(prompt)
        print(f"[llm] Gemini response received ({len(response.text)} chars)")
        return response.text.strip(), sources
    except Exception as e:
        print(f"[llm] ERROR - Gemini generation failed ({type(e).__name__}): {e} - falling back")
        if off_topic:
            # Falling back to the raw chunk here would leak an irrelevant
            # document instead of declining - use the canned redirect instead.
            return OFF_TOPIC_FALLBACK.get(language, OFF_TOPIC_FALLBACK["en"]), ""
        return _raw_fallback_text(), sources


def touch_session(session_id: str, title_candidate: str | None = None):
    """Create the chat_sessions row on first message, or bump updated_at on later ones.

    No row is created until the first message actually sends (avoids empty-session
    clutter from a passenger opening "+ New chat" and never typing anything).
    """
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
    """Extract a canonical train ID (e.g. PM-4082, IC-4665) from free text."""
    import re
    match = re.search(r"\b[A-Z]{2,12}-\d{3,5}\b", text, re.IGNORECASE)
    return match.group(0).upper() if match else ""


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/trains/{train_id}/details")
def train_details(train_id: str):
    clean_id = train_id.strip().upper()
    if not re.fullmatch(r"[A-Z]{2,12}-\d{3,5}", clean_id):
        raise HTTPException(status_code=404, detail="Train not found")
    try:
        details = get_train_details(clean_id)
    except TrainRepositoryUnavailable:
        raise HTTPException(status_code=503, detail="Train details are temporarily unavailable")
    if details is None:
        raise HTTPException(status_code=404, detail="Train not found")
    return {"train": details, "updated_at": datetime.now(timezone.utc).isoformat()}


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

    source = "local"
    reply = ""
    delay_minutes = None
    action = None
    prefill = None
    cancellation = None

    if intent in ("schedule_query", "fare_query"):
        reply, source = compose_rag_answer(
            text, language, req.session_id,
            source_filter=INTENT_SOURCE_DOC[intent], intent=intent, entities=entities,
        )

    elif intent == "train_info":
        train_id = entities.get("train_id")
        if not train_id:
            reply = "Please provide a train ID so I can check the canonical train registry."
            source = "via Shared Train Registry"
        else:
            try:
                train = await asyncio.to_thread(get_train, train_id)
                if train is None:
                    reply = f"TRAIN_NOT_FOUND: {train_id} is not registered in the canonical train registry."
                else:
                    schedules = await asyncio.to_thread(get_train_schedule, train_id)
                    route = train.get("route") or "route not recorded"
                    active = "active" if train.get("active") else "inactive"
                    reply = (
                        f"{train.get('train_name') or train_id} ({train_id}) is {active}. "
                        f"Route: {route}. "
                        f"Maintenance status: {train.get('maintenance_status', 'UNKNOWN')}."
                    )
                    if schedules:
                        first = schedules[0]
                        reply += (
                            f" Next recorded service: {first.get('from_station')} to "
                            f"{first.get('to_station')} on {first.get('travel_date')} "
                            f"at {first.get('departure_time')}."
                        )
                source = "via Shared Train Registry"
            except TrainRepositoryUnavailable:
                reply = "The canonical train registry is temporarily unavailable."
                source = "via Shared Train Registry"

    elif intent == "delay_check":
        stations = entities.get("stations", [])
        route = " - ".join(stations) if isinstance(stations, list) and len(stations) >= 2 else "Colombo Fort - Kandy"
        train_id = entities.get("train_id")
        resolved_via_registry = False
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
        if not train_id:
            reply = "TRAIN_NOT_FOUND: provide a train ID so Operations can validate it."
            source = "via Operations Agent (Hub)"
            save_message(req.session_id, "user", text)
            save_message(req.session_id, "assistant", reply)
            return ChatResponse(session_id=req.session_id, reply=reply, intent=intent, language=language, entities=entities, source=source)
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
            },
        )
        hub_response = await send_to_hub(envelope)
        if hub_response.status == "ok":
            p = hub_response.payload
            # Operations' /hub/message hands back structured fields, not one
            # composed sentence (unlike Maintenance/Booking below) - this
            # assembles them, it doesn't re-run anything through an LLM.
            delay = p.get("predicted_delay_minutes", 0)
            delay_minutes = float(delay)
            reason = p.get("reason") or p.get("explanation", "Operational congestion")
            similar = p.get("similar_incident")
            if not similar and p.get("similar_past_incidents"):
                similar = p["similar_past_incidents"][0]
            if not similar:
                similar = "No similar historical incident recorded"

            # When M2 flags a maintenance-related cause, also query M4 via
            # Hub — the passenger gets the live maintenance record (reason,
            # ETA) in the same reply, not just the delay prediction.
            _MAINT_KEYWORDS = {"maintenance", "repair", "fault", "breakdown", "mechanical", "out of service"}
            maintenance_context = ""
            if train_id and any(kw in reason.lower() for kw in _MAINT_KEYWORDS):
                try:
                    maint_envelope = build_envelope(
                        receiver_agent="maintenance-agent",
                        intent="train_status_query",
                        payload={"train_id": train_id, "raw_text": text},
                    )
                    maint_response = await send_to_hub(maint_envelope)
                    if maint_response.status == "ok":
                        mp = maint_response.payload
                        if mp.get("under_maintenance"):
                            eta_note = (
                                f" Expected back in service by {mp['estimated_clear']}."
                                if mp.get("estimated_clear")
                                else ""
                            )
                            maintenance_context = (
                                f" Maintenance update: "
                                f"{mp.get('reason', 'Technical issue under investigation')}.{eta_note}"
                            )
                except Exception:
                    pass

            reply = (
                f"Expected delay: {delay} minutes. "
                f"Reason: {reason}.{maintenance_context} "
                f"Similar past incident: {similar}."
            )
            source = "via Operations Agent + Maintenance Agent (Hub)" if maintenance_context else "via Operations Agent (Hub)"
        else:
            fallback = DELAY_UNREACHABLE_REPLIES.get(language, DELAY_UNREACHABLE_REPLIES["en"])
            message = hub_response.message or fallback
            # TRAIN_NOT_FOUND is a cross-team sentinel M2 also emits - passed
            # through verbatim rather than localized, since something downstream
            # may match on that exact prefix.
            reply = message if "TRAIN_NOT_FOUND" in message else fallback
            source = "via Operations Agent (Hub)"

    elif intent == "train_status":
        train_id = entities.get("train_id") or _extract_train_id(text)
        if not train_id:
            reply = "Please provide a train ID (e.g. PM-4082) so I can check its status."
            source = "local"
        else:
            try:
                canonical = await asyncio.to_thread(get_train, train_id)
                if canonical is None:
                    reply = f"TRAIN_NOT_FOUND: {train_id} is not a recognised train service."
                    source = "via Shared Train Registry"
                else:
                    envelope = build_envelope(
                        receiver_agent="maintenance-agent",
                        intent="train_status_query",
                        payload={"train_id": train_id, "raw_text": text},
                    )
                    hub_response = await send_to_hub(envelope)
                    if hub_response.status == "ok":
                        p = hub_response.payload
                        reply = p.get("message", "I could not retrieve the train status right now.")
                    else:
                        reply = "I couldn't check the train status right now. Please try again shortly."
                    source = "via Maintenance Agent"
            except TrainRepositoryUnavailable:
                reply = "The train registry is temporarily unavailable. Please try again."
                source = "via Shared Train Registry"

    elif intent == "complaint":
        envelope = build_envelope(
            receiver_agent="maintenance-agent",
            intent="issue_report",
            payload={"description": text, "train_id": entities.get("train_id", "")},
        )
        hub_response = await send_to_hub(envelope)
        if hub_response.status == "ok":
            p = hub_response.payload
            # Maintenance's reply text is already composed by that agent - passed
            # through as-is, just appending the ticket id for the passenger's reference.
            reply = f"{p['message']} (Ticket: {p['ticket_id']})"
            source = "via Maintenance Agent"
        else:
            reply = hub_response.message or "I couldn't log your issue right now."

    elif intent == "booking_request":
        from_st = entities.get("from_station")
        to_st = entities.get("to_station")
        t_date = entities.get("travel_date")
        prefill = {}
        if from_st:
            prefill["from_station"] = from_st
        if to_st:
            prefill["to_station"] = to_st
        if t_date:
            prefill["travel_date"] = t_date

        params = []
        if from_st:
            params.append(f"from={from_st}")
        if to_st:
            params.append(f"to={to_st}")
        if t_date:
            params.append(f"date={t_date}")
        query_str = f"?{'&'.join(params)}" if params else ""
        booking_url = f"http://localhost:3000/user/booking{query_str}"

        action = {
            "type": "continue_to_booking",
            "label": "Continue to Booking ➔",
            "url": booking_url,
            "prefill": prefill,
        }

        envelope = build_envelope(
            receiver_agent="booking-agent",
            intent="booking_request",
            payload={
                "from_station": entities.get("from_station"),
                "to_station": entities.get("to_station"),
                "travel_date": entities.get("travel_date"),
                "train_id": entities.get("train_id"),
                "seat_class": entities.get("seat_class"),
                # ner_extractor now returns None (not 1) when no count was
                # mentioned - booking_request isn't part of these fixes, so
                # this preserves its prior default-to-1 behavior exactly.
                # entities.get("passenger_count", 1) would NOT catch this,
                # since the key is present with value None, not missing.
                "passenger_count": entities.get("passenger_count") or 1,
            },
        )
        hub_response = await send_to_hub(envelope)
        if hub_response.status == "ok":
            reply = hub_response.payload.get("message", "Booking request processed.")
            source = "via Booking Agent"
        else:
            details_list = []
            if from_st:
                details_list.append(f"from **{from_st}**")
            if to_st:
                details_list.append(f"to **{to_st}**")
            if t_date:
                details_list.append(f"on **{t_date}**")
            if details_list:
                reply = (
                    f"I found your booking request {' '.join(details_list)}. "
                    "Click the button below to proceed to the reservation desk with these details pre-filled."
                )
            else:
                reply = (
                    "I can help you book a train ticket! "
                    "Click the button below to open the booking desk and select your route and date."
                )
            source = "via Booking Agent"

    elif intent == "cancel_booking":
        booking_ref = entities.get("booking_reference") or _extract_train_id(text)
        reason = entities.get("reason") or "No reason provided"
        ref_display = booking_ref or "Reference Required"

        reply = (
            f"I have prepared your cancellation request for booking **{ref_display}** "
            f"with reason: *\"{reason}\"*. Please review the confirmation card below and click **Send Cancellation Request**."
        )
        cancellation = {
            "booking_reference": booking_ref or "",
            "reason": reason,
        }
        action = {
            "type": "cancellation_confirmation_card",
            "label": "Send Cancellation Request ➔",
            "booking_reference": booking_ref or "",
            "reason": reason,
        }
        source = "via Booking Agent (Hub)"

    else:
        # Natural route questions can miss the keyword classifier. Resolve them
        # against the shared registry before falling back to FAQ retrieval.
        route_words = text.lower()
        if len(entities.get("stations", [])) >= 2 and "train" in route_words:
            origin, destination = entities["stations"][:2]
            try:
                services = await asyncio.to_thread(search_trains, origin, destination)
                if services:
                    service_lines = [
                        f"{service.get('train_id') or 'N/A'} — {service.get('train_name') or 'N/A'}"
                        for service in services[:10]
                    ]
                    reply = (
                        f"I found {len(services)} train service(s) from {origin} to {destination}:\n"
                        + "\n".join(f"- {line}" for line in service_lines)
                    )
                    source = "via Shared Train Registry"
                else:
                    reply = f"I couldn't find a shared train service from {origin} to {destination}."
                    source = "via Shared Train Registry"
            except TrainRepositoryUnavailable:
                reply = "The shared train registry is temporarily unavailable. Please try again shortly."
                source = "via Shared Train Registry"
        else:
            # Keyword classifier missed this one - try the FAQ docs before giving up.
            # compose_rag_answer() already returns a clear "not found, try rephrasing"
            # message (with source="") when nothing relevant is retrieved.
            reply, source = compose_rag_answer(text, language, req.session_id, intent=intent, entities=entities)

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
        supabase.table("chat_sessions").delete().eq("session_id", session_id).execute()
    except Exception as e:
        print(f"Supabase delete failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete session")
    return None


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
