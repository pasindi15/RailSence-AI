"""
tests/test_chat.py
Phase 1 tests: health check, input sanitization, and that /chat is wired
correctly. The LLM call itself is mocked so tests don't need a real API key
or make real network calls.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["agent"] == "passenger-agent"


def test_chat_rejects_empty_message():
    resp = client.post("/chat", json={"message": ""})
    assert resp.status_code == 422


def test_chat_rejects_script_injection():
    resp = client.post("/chat", json={"message": "<script>alert(1)</script>"})
    assert resp.status_code == 422


def test_chat_rejects_oversized_message():
    resp = client.post("/chat", json={"message": "a" * 2000})
    assert resp.status_code == 422


def test_chat_happy_path():
    with patch("main.generate_reply", new=AsyncMock(return_value="This is a mocked reply.")):
        resp = client.post("/chat", json={"message": "Hello, when is the next train?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == "This is a mocked reply."
    assert "session_id" in body


def test_feedback_accepts_valid_rating():
    resp = client.post(
        "/feedback",
        json={"session_id": "abc123", "rating": "up"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "recorded"


def test_feedback_rejects_invalid_rating():
    resp = client.post(
        "/feedback",
        json={"session_id": "abc123", "rating": "sideways"},
    )
    assert resp.status_code == 422


def test_chat_works_when_db_not_configured():
    """If Supabase env vars are missing, /chat must still succeed —
    persistence failures should never break the chat itself."""
    with patch("main.generate_reply", new=AsyncMock(return_value="Reply without DB.")):
        resp = client.post("/chat", json={"message": "Does this still work without a DB?"})
    assert resp.status_code == 200
    assert resp.json()["reply"] == "Reply without DB."
