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
from nlu.intent_classifier import classify_intent
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
        if not train_id:
            reply = "TRAIN_NOT_FOUND: provide a train ID so Operations can validate it."
            source = "via Operations Agent (Hub)"
            save_message(req.session_id, "user", text)
            save_message(req.session_id, "assistant", reply)
            return ChatResponse(session_id=req.session_id, reply=reply, intent=intent, language=language, entities=entities, source=source)
        envelope = build_envelope(
            receiver_agent="operations-agent",
            intent="delay_check",
            payload={
                "stations": stations,
                "time": entities.get("time"),
                "raw_text": text,
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
            message = hub_response.message or "I couldn't reach the Operations Agent right now."
            reply = message if "TRAIN_NOT_FOUND" in message else "I couldn't reach the Operations Agent right now."
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
                "passenger_count": entities.get("passenger_count", 1),
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
