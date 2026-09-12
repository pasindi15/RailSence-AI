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
import uuid
from pathlib import Path
from datetime import datetime, timezone

import google.generativeai as genai
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

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system_prompt.md").read_text(encoding="utf-8")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini_model = None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-flash-latest", system_instruction=SYSTEM_PROMPT)

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


def compose_rag_answer(text: str, language: str, session_id: str) -> tuple[str, str]:
    """Retrieve top FAQ chunks and have Gemini compose a grounded natural-language reply."""
    chunks = retrieve_faq_chunks(text, top_k=3)
    if not chunks:
        return "I don't have that information yet.", ""

    sources = ", ".join(sorted({c["source"] for c in chunks}))

    if not gemini_model:
        return f"Here's what I found:\n\n{chunks[0]['text'][:400]}", sources

    history = get_recent_history(session_id)
    history_text = "\n".join(f"{h['role']}: {h['message']}" for h in history) or "(no prior messages)"
    context_text = "\n\n---\n\n".join(f"[{c['source']}] {c['text']}" for c in chunks)

    prompt = (
        f"language: {language}\n\n"
        f"Conversation history:\n{history_text}\n\n"
        f"Retrieved context:\n{context_text}\n\n"
        f"User question: {text}"
    )

    try:
        response = gemini_model.generate_content(prompt)
        return response.text.strip(), sources
    except Exception as e:
        print(f"Gemini generation failed: {e}")
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

    language = detect_language(text)
    intent = classify_intent(text)
    entities = extract_entities(text)

    source = "local"
    reply = ""

    if intent in ("schedule_query", "fare_query"):
        reply, source = compose_rag_answer(text, language, req.session_id)

    elif intent == "delay_check":
        envelope = build_envelope(
            receiver_agent="operations-agent",
            intent="delay_check",
            payload={"stations": entities["stations"], "time": entities["time"], "raw_text": text},
        )
        hub_response = await send_to_hub(envelope)
        if hub_response.get("status") == "ok":
            p = hub_response["payload"]
            reply = (
                f"Expected delay: {p['predicted_delay_minutes']} minutes. "
                f"Reason: {p['reason']}. Similar past incident: {p['similar_incident']}."
            )
            source = "via Operations Agent"
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
        reply = "I can help with schedules, fares, delays, bookings, or reporting an issue. Could you rephrase your question?"

    save_message(req.session_id, "user", text)
    save_message(req.session_id, "assistant", reply)

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
