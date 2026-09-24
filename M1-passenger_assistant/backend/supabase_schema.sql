-- ===========================================================================
-- RailSense AI — Member A (Passenger Assistant) Supabase schema additions
-- Adds session-level metadata (title, pin state) needed for sidebar chat
-- management (pin / delete / list). `chat_messages` and `feedback` already
-- exist in the project's Supabase instance and are not redefined here.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'New conversation',
    is_pinned BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_chat_sessions_pinned_updated
    ON chat_sessions (is_pinned DESC, updated_at DESC);

-- chat_messages.session_id is already a free-text column (no FK today).
-- NOT VALID skips checking pre-existing rows (there's likely years of test
-- data with no matching chat_sessions row) so this migration can't fail on
-- them, while still enforcing the FK for all new/updated rows going forward.
-- The DELETE /chat/{session_id} endpoint does NOT rely on this cascade - it
-- deletes chat_messages then chat_sessions explicitly, so hard-delete works
-- correctly even on a database where this constraint didn't attach cleanly.
DO $$ BEGIN
    ALTER TABLE chat_messages
        ADD CONSTRAINT fk_chat_messages_session
        FOREIGN KEY (session_id) REFERENCES chat_sessions (session_id) ON DELETE CASCADE
        NOT VALID;
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Rolling conversation summaries used by /chat for context (see
-- get_conversation_context in main.py). One row per session; `turns_covered`
-- is how many completed turns the summary already includes. Run this in the
-- Supabase SQL editor - until it exists the backend just keeps summaries in memory.
CREATE TABLE IF NOT EXISTS chat_summaries (
    session_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    turns_covered INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
