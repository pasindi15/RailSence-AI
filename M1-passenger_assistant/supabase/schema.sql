-- passenger-agent/supabase/schema.sql
-- Run this in the Supabase SQL editor (Project → SQL Editor → New query)
-- before starting the server, so /chat and /feedback have tables to write to.

create table if not exists messages (
  id bigint generated always as identity primary key,
  session_id text not null,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_messages_session_id on messages (session_id);

create table if not exists feedback (
  id bigint generated always as identity primary key,
  session_id text not null,
  rating text not null check (rating in ('up', 'down')),
  comment text,
  created_at timestamptz not null default now()
);

create index if not exists idx_feedback_session_id on feedback (session_id);

-- Note: RLS (Row Level Security) is left disabled here since the backend
-- writes using the SUPABASE_SECRET_KEY (service-role key), which bypasses
-- RLS by design. Never expose SUPABASE_SECRET_KEY to the frontend — only
-- SUPABASE_PUBLISHABLE_KEY is safe client-side, and only if you add RLS
-- policies before using it that way.
