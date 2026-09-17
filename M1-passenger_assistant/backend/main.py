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
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

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
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client

from nlu.lang_detect import detect_language
from nlu.intent_classifier import classify_intent
from nlu.ner_extractor import extract_entities
from hub_client import build_envelope, send_to_hub
from rag.retriever import retrieve_faq_chunks

# load_dotenv() with no path searches upward from the CWD, not from this
# file's location - if uvicorn is ever launched from outside backend/, that
# silently finds no .env, GEMINI_API_KEY stays None, and /chat falls back to
# raw RAG chunk text with zero errors. Anchor it to this file instead.
load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

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


class FeedbackRequest(BaseModel):
    session_id: str
    rating: int
    comment: str | None = None


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
        return (
            "I don't have that information in my current knowledge base. "
            "Could you rephrase, or ask about schedules, fares, delays, or bookings instead?"
        ), ""

    sources = ", ".join(sorted({c["source"] for c in chunks}))

    if not gemini_model:
        print("[llm] SKIPPED - gemini_model is None (GEMINI_API_KEY missing/not loaded) - returning raw RAG chunk text")
        return f"Here's what I found:\n\n{chunks[0]['text'][:400]}", sources

    history = get_recent_history(session_id)
    history_text = "\n".join(f"{h['role']}: {h['message']}" for h in history) or "(no prior messages)"
    context_text = "\n\n---\n\n".join(f"[{c['source']}] {c['text']}" for c in chunks)
    # Only surface entities the NLU actually found - an empty/None-filled dict
    # would just add noise to the prompt instead of useful grounding signal.
    known_details = ", ".join(f"{k}={v}" for k, v in (entities or {}).items() if v) or "none extracted"

    prompt = (
        f"language: {language}\n\n"
        f"Detected intent: {intent}\n"
        f"Extracted details from the passenger's message: {known_details}\n\n"
        f"Conversation history:\n{history_text}\n\n"
        f"Retrieved knowledge base context:\n{context_text}\n\n"
        f"Passenger's question: {text}"
    )

    print("[llm] Gemini request started (gemini-flash-latest)")
    try:
        response = gemini_model.generate_content(prompt)
        print(f"[llm] Gemini response received ({len(response.text)} chars)")
        return response.text.strip(), sources
    except Exception as e:
        print(f"[llm] ERROR - Gemini generation failed ({type(e).__name__}): {e} - falling back to raw RAG chunk text")
        return f"Here's what I found:\n\n{chunks[0]['text'][:400]}", sources


def save_message(session_id: str, role: str, message: str):
    if not supabase:
        print("Warning: Supabase is not configured.")
        return

    try:
        supabase.table("chat_messages").insert({
            "session_id": session_id,
            "role": role,
            "message": message,
        }).execute()
    except Exception as e:
        print(f"Supabase save failed: {e}")


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    text = req.message.strip()
    print(f"[chat] received message={text!r} session_id={req.session_id}")

    language = detect_language(text)
    intent = classify_intent(text)
    entities = extract_entities(text)
    print(f"[chat] language={language} intent={intent}")

    source = "local"
    reply = ""

    if intent in ("schedule_query", "fare_query"):
        reply, source = compose_rag_answer(
            text, language, req.session_id,
            source_filter=INTENT_SOURCE_DOC[intent], intent=intent, entities=entities,
        )

    elif intent == "delay_check":
        stations = entities.get("stations", [])
        route = " - ".join(stations) if isinstance(stations, list) and len(stations) >= 2 else "Colombo Fort - Kandy"
        envelope = build_envelope(
            receiver_agent="operations-agent",
            intent="delay_check",
            payload={
                "stations": stations,
                "time": entities.get("time"),
                "raw_text": text,
                "route": route,
                "train_id": entities.get("train_id", "PM-4082"),
            },
        )
        hub_response = await send_to_hub(envelope)
        if hub_response.get("status") == "ok":
            p = hub_response.get("payload", {})
            delay = p.get("predicted_delay_minutes", 0)
            reason = p.get("reason") or p.get("explanation", "Operational congestion")
            similar = p.get("similar_incident")
            if not similar and p.get("similar_past_incidents"):
                similar = p["similar_past_incidents"][0]
            if not similar:
                similar = "No similar historical incident recorded"
            reply = (
                f"Expected delay: {delay} minutes. "
                f"Reason: {reason}. "
                f"Similar past incident: {similar}."
            )
            source = "via Operations Agent (Hub)"
        else:
            reply = "I couldn't reach the Operations Agent right now."

    elif intent == "complaint":
        envelope = build_envelope(
            receiver_agent="maintenance-agent",
            intent="issue_report",
            payload={"description": text},
        )
        hub_response = await send_to_hub(envelope)
        if hub_response.get("status") == "ok":
            p = hub_response["payload"]
            reply = f"{p['message']} (Ticket: {p['ticket_id']})"
            source = "via Maintenance Agent"
        else:
            reply = "I couldn't log your issue right now."

    elif intent == "booking_request":
        envelope = build_envelope(
            receiver_agent="booking-agent",
            intent="booking_request",
            payload={
                "from_station": entities["from_station"],
                "to_station": entities["to_station"],
                "travel_date": entities["travel_date"],
                "train_id": entities["train_id"],
                "seat_class": entities["seat_class"],
                "passenger_count": entities["passenger_count"],
            },
        )
        hub_response = await send_to_hub(envelope)
        if hub_response.get("status") == "ok":
            p = hub_response["payload"]
            reply = p["message"]
            source = "via Booking Agent"
        else:
            reply = "I couldn't reach the Booking Agent right now."

    else:
        # Keyword classifier missed this one - try the FAQ docs before giving up.
        # compose_rag_answer() already returns a clear "not found, try rephrasing"
        # message (with source="") when nothing relevant is retrieved, so no
        # separate override is needed here.
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
    )


@app.get("/chat/{session_id}/history")
def history(session_id: str):
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
