-- M2 Admin Dashboard — additive schema.
-- Safe to run in the same Supabase project as supabase_phase5_schema.sql.
-- Does NOT modify operations_history, incident_embeddings, audit_events,
-- or operational_events — only adds new tables.

-- ---------------------------------------------------------------------
-- incident_reports: reviewable queue for POST /incident-report submissions
-- ---------------------------------------------------------------------
create table if not exists incident_reports (
    incident_id     uuid primary key default gen_random_uuid(),
    train_id        text,
    station         text,
    raw_text        text,
    summary         text,
    classified_type text,
    nlp_method      text,
    review_status   text default 'pending',   -- pending | approved | rejected | corrected
    reviewed_by     text,
    reviewed_at     double precision,
    received_at     timestamptz default now()
);

create index if not exists idx_incident_reports_status on incident_reports (review_status);
create index if not exists idx_incident_reports_received on incident_reports (received_at desc);

-- Optional: in main.py's /incident-report handler, after producing the
-- summary + classification, also insert a row here, e.g.:
--
--   supabase_store.get_client().table("incident_reports").insert({
--       "train_id": payload.train_id,
--       "station": payload.station,
--       "raw_text": payload.text,
--       "summary": summary,
--       "classified_type": classified_type,
--       "nlp_method": nlp_method,
--   }).execute()
--
-- This is optional — the admin dashboard works standalone even if you
-- don't wire this in, it will just show an empty queue until you do.

-- ---------------------------------------------------------------------
-- model_training_runs: history of retrain events (mirrors local JSON log)
-- ---------------------------------------------------------------------
create table if not exists model_training_runs (
    id              bigint generated always as identity primary key,
    triggered_by    text,
    returncode      int,
    metrics         jsonb,
    action          text default 'retrain',   -- retrain | rollback
    restored_from   text,
    created_at      timestamptz default now()
);

-- ---------------------------------------------------------------------
-- admin_config: small key/value settings store (e.g. alert threshold)
-- ---------------------------------------------------------------------
create table if not exists admin_config (
    key    text primary key,
    value  jsonb
);

-- ---------------------------------------------------------------------
-- admin_users: optional — only needed if you move admin login into
-- Supabase instead of the env-var-based placeholder in admin_auth.py
-- ---------------------------------------------------------------------
create table if not exists admin_users (
    username      text primary key,
    password_hash text not null,
    created_at    timestamptz default now()
);
