-- RailSense Phase 1, 4 and 5 Supabase migration.
-- Run this in Supabase SQL Editor before importing data or embeddings.

create extension if not exists vector;

create table if not exists public.operations_history (
    record_id uuid primary key,
    route text not null,
    station text not null,
    train_id text not null,
    scheduled_time timestamptz not null,
    actual_time timestamptz not null,
    weather text not null,
    day_type text not null,
    incident_type text not null,
    incident_note text not null default '',
    delay_minutes double precision not null,
    created_at timestamptz not null default now(),
    constraint operations_history_delay_range check (delay_minutes >= -2)
);

create index if not exists operations_history_route_idx on public.operations_history(route);
create index if not exists operations_history_station_idx on public.operations_history(station);
create index if not exists operations_history_scheduled_idx on public.operations_history(scheduled_time);
create index if not exists operations_history_incident_idx on public.operations_history(incident_type);

create table if not exists public.incident_embeddings (
    record_id uuid primary key references public.operations_history(record_id) on delete cascade,
    route text not null,
    station text not null,
    incident_type text not null,
    delay_minutes double precision not null,
    incident_note text not null,
    embedding vector(384) not null,
    created_at timestamptz not null default now()
);

create index if not exists incident_embeddings_embedding_idx
on public.incident_embeddings using ivfflat (embedding vector_cosine_ops)
with (lists = 50);

create or replace function public.match_incidents(
    query_embedding vector(384),
    match_count int default 3
)
returns table (
    record_id uuid,
    route text,
    station text,
    incident_type text,
    delay_minutes double precision,
    incident_note text,
    similarity double precision
)
language sql stable
security definer
set search_path = public
as $$
    select i.record_id, i.route, i.station, i.incident_type,
           i.delay_minutes, i.incident_note,
           1 - (i.embedding <=> query_embedding) as similarity
    from public.incident_embeddings as i
    order by i.embedding <=> query_embedding
    limit least(greatest(coalesce(match_count, 3), 1), 5);
$$;

create table if not exists public.audit_events (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    action text not null,
    agent_name text not null default 'operations-agent',
    sender_agent text,
    receiver_agent text,
    route text,
    train_id text,
    predicted_delay_minutes double precision,
    model_version text,
    classified_type text,
    metadata jsonb not null default '{}'::jsonb
);

create index if not exists audit_events_created_idx on public.audit_events(created_at desc);
create index if not exists audit_events_action_idx on public.audit_events(action);
create index if not exists audit_events_route_idx on public.audit_events(route);

create table if not exists public.operational_events (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    event_type text not null,
    sender_agent text not null default 'operations-agent',
    route text,
    train_id text,
    severity text not null default 'warning',
    payload jsonb not null default '{}'::jsonb,
    published_destinations text[] not null default '{}'
);

create index if not exists operational_events_created_idx on public.operational_events(created_at desc);
create index if not exists operational_events_type_idx on public.operational_events(event_type);
create index if not exists operational_events_route_idx on public.operational_events(route);

-- Extensible operational control-center entities. Each row keeps its stable id
-- and entity type relational, while the evolving dashboard fields live in JSONB.
create table if not exists public.operation_entities (
    id text primary key,
    entity_type text not null,
    data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists operation_entities_type_idx on public.operation_entities(entity_type);
create index if not exists operation_entities_updated_idx on public.operation_entities(updated_at desc);

alter table public.operations_history enable row level security;
alter table public.incident_embeddings enable row level security;
alter table public.audit_events enable row level security;
alter table public.operational_events enable row level security;
alter table public.operation_entities enable row level security;

drop policy if exists operations_history_read_authenticated on public.operations_history;
create policy operations_history_read_authenticated
on public.operations_history for select to authenticated using (true);

drop policy if exists incident_embeddings_read_authenticated on public.incident_embeddings;
create policy incident_embeddings_read_authenticated
on public.incident_embeddings for select to authenticated using (true);

drop policy if exists audit_events_read_authenticated on public.audit_events;
create policy audit_events_read_authenticated
on public.audit_events for select to authenticated using (true);

drop policy if exists operational_events_read_authenticated on public.operational_events;
create policy operational_events_read_authenticated
on public.operational_events for select to authenticated using (true);

drop policy if exists operation_entities_read_authenticated on public.operation_entities;
create policy operation_entities_read_authenticated
on public.operation_entities for select to authenticated using (true);