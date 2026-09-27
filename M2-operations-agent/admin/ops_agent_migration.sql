-- Operations Assistant history — additive migration.
-- Run once in the Supabase SQL editor. Safe to re-run.
-- Until it is applied, M2 keeps history in data/ops_agent_queries.jsonl.

create table if not exists ops_agent_queries (
    id              uuid primary key default gen_random_uuid(),
    admin_user_id   text not null,
    question        text not null,
    answer          text not null,
    answer_type     text not null default 'answer',  -- answer | restricted | insufficient_data | out_of_scope | unavailable
    tool_calls_made jsonb not null default '[]'::jsonb,
    sources         jsonb not null default '[]'::jsonb,
    highlights      jsonb not null default '[]'::jsonb,
    created_at      timestamptz not null default now()
);

-- Added after the first version of this file; harmless if already present.
alter table ops_agent_queries add column if not exists answer_type text not null default 'answer';
-- Which path produced the answer (llm_tool_calling | rule_based_fallback | template_after_guard);
-- drives the technique badges when an answer is replayed from history.
alter table ops_agent_queries add column if not exists answer_method text;

-- History is always read per officer, newest first.
create index if not exists idx_ops_agent_queries_user
    on ops_agent_queries (admin_user_id, created_at desc);
