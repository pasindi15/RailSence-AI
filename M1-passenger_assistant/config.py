"""
config.py
Loads environment variables for the Passenger Assistant Agent.
Phase 1: just enough to make one LLM call and run the FastAPI app.
Phase 2 will add Chroma / embedding-related settings (already stubbed below).
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # --- Service identity ---
    AGENT_NAME: str = "passenger-agent"
    APP_ENV: str = os.getenv("APP_ENV", "development")

    # --- LLM ---
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")  # "openai" | "anthropic"
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")

    # --- Hub (Member C's service) ---
    HUB_URL: str = os.getenv("HUB_URL", "http://localhost:8000")
    HUB_TIMEOUT_SECONDS: float = float(os.getenv("HUB_TIMEOUT_SECONDS", "5"))

    # --- Auth ---
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")

    # --- RAG (used from Phase 2 onward, kept here so config never has to move) ---
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_store")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    # --- Server ---
    PORT: int = int(os.getenv("PORT", "8001"))

    # --- Supabase (backend DB: chat history + feedback persistence) ---
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SECRET_KEY: str = os.getenv("SUPABASE_SECRET_KEY", "")
    SUPABASE_PUBLISHABLE_KEY: str = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    SUPABASE_JWKS_URL: str = os.getenv("SUPABASE_JWKS_URL", "")


settings = Settings()


def validate_settings() -> list[str]:
    """Returns a list of human-readable warnings for missing required config.
    Called once at startup so misconfiguration fails loudly, not silently."""
    warnings = []
    if not settings.LLM_API_KEY:
        warnings.append(
            "LLM_API_KEY is not set. /chat will fail until it's added to .env"
        )
    return warnings
