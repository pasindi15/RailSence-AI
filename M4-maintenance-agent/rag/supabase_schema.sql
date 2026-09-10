-- M4 Maintenance Agent — pgvector schema for equipment manual embeddings
-- Run this in the Supabase SQL editor AFTER enabling the vector extension.

create extension if not exists vector;

-- Equipment manual sections with embeddings (all-MiniLM-L6-v2, 384 dims)
create table if not exists manual_embeddings (
    id           uuid primary key default gen_random_uuid(),
    section_id   text unique not null,
    manual       text not null,
    section_title text not null,
    content      text not null,
    source_file  text not null,
    embedding    vector(384),
    created_at   timestamptz default now()
);

create index if not exists manual_embeddings_embedding_idx
    on manual_embeddings
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 50);

-- RPC: retrieve top-k similar manual sections
create or replace function match_manual_sections(
    query_embedding vector(384),
    match_count     int default 3
)
returns table (
    id            uuid,
    section_id    text,
    manual        text,
    section_title text,
    content       text,
    source_file   text,
    score         float
)
language sql stable
as $$
    select
        id,
        section_id,
        manual,
        section_title,
        content,
        source_file,
        1 - (embedding <=> query_embedding) as score
    from manual_embeddings
    order by embedding <=> query_embedding
    limit match_count;
$$;
