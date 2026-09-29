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

-- ===========================================================================
-- Per-passenger chat history (multi-user ownership)
-- ===========================================================================
-- Before this, chat_sessions had no owner column, so GET /chat returned every
-- session in the table to every caller - any passenger could read, rename,
-- pin or delete any other passenger's conversation. These additions give each
-- row an owner, which the backend fills in from the verified JWT (never from
-- anything the browser sends).
--
-- Everything below is ADDITIVE: no DROP, no data deletion, no type change.
-- Existing rows keep user_id = NULL, which means "owned by nobody" - they stay
-- in the database but no longer appear in any signed-in passenger's sidebar.
-- Safe to re-run; every statement is guarded.

-- Login accounts for the M1 chat app. Replaces the hardcoded PASSENGER_ACCOUNTS
-- array that used to sit in the frontend bundle with plaintext passwords.
--
-- NOTE ON THE NAME: this is `passenger_accounts`, not `passengers`. The
-- `passengers` table already exists and belongs to M3's booking agent - it is
-- keyed by a SERIAL id, identifies travellers by NIC hash (nic_hash,
-- nic_masked, dob, phone), holds real booking records, and is the target of a
-- foreign key from booking_passengers. Login accounts are a different concern
-- with a different key, so they get their own table and M3's schema and rows
-- are never touched. (An earlier draft of this migration reused the name; the
-- CREATE TABLE IF NOT EXISTS silently did nothing and the INSERT then failed
-- with: column "user_id" of relation "passengers" does not exist.)
CREATE TABLE IF NOT EXISTS passenger_accounts (
    user_id       TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,          -- bcrypt, cost 12
    full_name     TEXT NOT NULL,
    nic           TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The four demo accounts, with the same usernames/passwords as before so no
-- existing demo script or slide deck has to change. ON CONFLICT DO NOTHING
-- means re-running this never overwrites a password you later changed.
INSERT INTO passenger_accounts (user_id, username, password_hash, full_name, nic) VALUES
    ('PSG-001', 'kavya', '$2b$12$z8OjII6iPJvqDMX1zlb4SO6K2QJiC9hScY6qaxr/H2aULtqpuCsou', 'Kavya Perera', '200012345678'),
    ('PSG-002', 'dilshan', '$2b$12$qT8bfLMjTA0NgysuKp3vSOuVREQUYlnJrVc2eh9WdEPOhRJAcAqFa', 'Dilshan Silva', '199887654321'),
    ('PSG-003', 'nimal', '$2b$12$AfZUFhQiULVBpKHon9M0UOdHhVXP0XYXA4O6ZduYxezOJE4TynhtW', 'Nimal Fernando', '200198765432'),
    ('PSG-004', 'guest', '$2b$12$e4cQzo9i6IIZDjVoiGFz.ODilOdATrPraW4FGgTr4ctODzYpsjY3q', 'Guest Passenger', 'N/A')
ON CONFLICT (user_id) DO NOTHING;

-- Owner columns. chat_sessions.user_id is the authoritative one - every
-- ownership check and sidebar filter reads it. chat_messages.user_id is
-- denormalised for auditing and defence in depth.
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS user_id TEXT;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS user_id TEXT;

-- Matches the sidebar query exactly: filter by owner, pinned first, newest first.
CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_pinned_updated
    ON chat_sessions (user_id, is_pinned DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_chat_messages_user
    ON chat_messages (user_id);

-- Optional second layer. RLS has NO effect on the backend today, because M1
-- connects with the service-role key, which bypasses RLS by design - the real
-- protection is the user_id filter and the ownership check in main.py. Enable
-- this only so that any future client using the anon/publishable key is denied
-- by default rather than allowed.
--   ALTER TABLE chat_sessions       ENABLE ROW LEVEL SECURITY;
--   ALTER TABLE chat_messages       ENABLE ROW LEVEL SECURITY;
--   ALTER TABLE passenger_accounts  ENABLE ROW LEVEL SECURITY;
