-- RailSense AI — M2 Operations Officers & RBAC Schema
-- Safe to execute against the RailSense AI Supabase Postgres instance.

create table if not exists officers (
    id              uuid primary key default gen_random_uuid(),
    full_name       varchar(255) not null,
    email           varchar(255) not null unique,
    password_hash   text not null,
    role            varchar(64) not null default 'operations_engineer',
    status          varchar(32) not null default 'active',  -- 'active' | 'inactive'
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    last_login_at   timestamptz,
    created_by      varchar(255)
);

create index if not exists idx_officers_email on officers (email);
create index if not exists idx_officers_role on officers (role);
create index if not exists idx_officers_status on officers (status);

create table if not exists officer_audit_logs (
    id                  uuid primary key default gen_random_uuid(),
    timestamp           timestamptz not null default now(),
    action              varchar(64) not null,  -- LOGIN, LOGOUT, OFFICER_CREATED, OFFICER_UPDATED, ROLE_CHANGED, OFFICER_DEACTIVATED, PASSWORD_RESET, UNAUTHORIZED_ACCESS_ATTEMPT
    actor_id            varchar(128),
    actor_name          varchar(255),
    actor_email         varchar(255),
    actor_role          varchar(64),
    target_officer_id   varchar(128),
    target_officer_email varchar(255),
    details             jsonb default '{}'::jsonb,
    ip_address          varchar(64)
);

create index if not exists idx_officer_audit_logs_timestamp on officer_audit_logs (timestamp desc);
create index if not exists idx_officer_audit_logs_action on officer_audit_logs (action);
