"""
main.py
Passenger Assistant Agent — FastAPI entrypoint.

PHASE 1 SCOPE (this file, right now):
  - /health returns service status
  - /chat takes a sanitized message and returns ONE raw LLM reply
    (no RAG, no intent routing, no Hub calls yet — that's Phase 2/3)
  - /feedback accepts and logs a thumbs up/down (in-memory for now)

Run it:
    uvicorn main:app --reload --port 8001
"""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import settings, validate_settings
from schemas import ChatRequest, ChatResponse, FeedbackRequest, HealthResponse
from llm_client import generate_reply, LLMError
import db_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("passenger-agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    warnings = validate_settings()
    for w in warnings:
        logger.warning(w)
    logger.info(f"{settings.AGENT_NAME} starting in {settings.APP_ENV} mode")
    yield


app = FastAPI(
    title="RailSense AI — Passenger Assistant Agent",
    version="0.1.0-phase1",
    lifespan=lifespan,
)

# Wide open for local dev against the Next.js frontend on a different port.
# Tighten this to specific origins before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

with open("prompts/system_prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", agent=settings.AGENT_NAME)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    try:
        reply_text = await generate_reply(
            system_prompt=SYSTEM_PROMPT,
            user_message=request.message,
        )
    except LLMError as e:
        logger.error(f"LLM call failed: {e}")
        raise HTTPException(status_code=502, detail=str(e))

    # Persist both turns. If Supabase isn't configured or is down, these
    # are no-ops (see db_client.py) — the chat reply is never blocked on this.
    await db_client.save_message(session_id, "user", request.message)
    await db_client.save_message(session_id, "assistant", reply_text)

    return ChatResponse(
        reply=reply_text,
        session_id=session_id,
        detected_language=None,   # wired in Phase 2
        intent=None,              # wired in Phase 2
        sources=[],               # wired in Phase 2 (RAG)
    )


@app.post("/feedback")
async def feedback(request: FeedbackRequest):
    await db_client.save_feedback(request.session_id, request.rating, request.comment)
    logger.info(f"Feedback received: {request.rating} for session {request.session_id}")
    return {"status": "recorded"}


@app.get("/chat/{session_id}/history")
async def chat_history(session_id: str):
    messages = await db_client.get_session_messages(session_id)
    return {"session_id": session_id, "messages": messages}
