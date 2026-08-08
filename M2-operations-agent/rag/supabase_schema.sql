-- Phase 4: run this in the Supabase SQL editor before embedding documents.
create extension if not exists vector;

create table if not exists incident_embeddings (
    record_id uuid primary key,
    route text not null,
    station text not null,
    incident_type text not null,
    delay_minutes double precision not null,
    incident_note text not null,
    embedding vector(384) not null
);

create index if not exists incident_embeddings_embedding_idx
on incident_embeddings using ivfflat (embedding vector_cosine_ops)
with (lists = 50);

create or replace function match_incidents (
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
as $$
    select
        i.record_id,
        i.route,
        i.station,
        i.incident_type,
        i.delay_minutes,
        i.incident_note,
        1 - (i.embedding <=> query_embedding) as similarity
    from incident_embeddings i
    order by i.embedding <=> query_embedding
    limit least(match_count, 5);
$$;
