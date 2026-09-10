-- M4 Maintenance Agent — Full Supabase schema
-- Run this in the Supabase SQL editor.
-- Also run rag/supabase_schema.sql for the pgvector manual embeddings table.

-- Asset maintenance history
create table if not exists assets_history (
    record_id           text primary key,
    asset_id            text not null,
    asset_type          text not null,
    station             text,
    route               text,
    last_service_date   date,
    days_since_service  int,
    fault_type          text,
    fault_count_30d     int default 0,
    health_score        numeric(5,2),
    health_status       text check (health_status in ('GREEN', 'AMBER', 'RED')),
    technician_note     text,
    recommended_action  text,
    -- sensor columns (nullable — not all apply to every asset type)
    temperature_celsius     numeric(6,1),
    vibration_level         numeric(5,2),
    oil_pressure_bar        numeric(5,2),
    fuel_efficiency_pct     numeric(5,1),
    axle_temp_celsius       numeric(6,1),
    wheel_profile_mm        numeric(6,1),
    pad_thickness_mm        numeric(5,1),
    brake_cylinder_pressure_bar numeric(5,2),
    stopping_distance_m     numeric(7,0),
    response_time_ms        numeric(7,0),
    voltage_output_v        numeric(5,1),
    contact_resistance_ohm  numeric(6,3),
    rail_wear_mm            numeric(5,2),
    gauge_deviation_mm      numeric(5,2),
    ballast_void_pct        numeric(5,1),
    motor_current_a         numeric(5,2),
    cycle_time_seconds      numeric(5,1),
    sensor_reliability_pct  numeric(5,1),
    created_at          timestamptz default now()
);

create index if not exists assets_history_asset_type_idx on assets_history (asset_type);
create index if not exists assets_history_station_idx on assets_history (station);
create index if not exists assets_history_health_status_idx on assets_history (health_status);

-- Audit events (shared table with other agents — agent_name differentiates)
create table if not exists audit_events (
    id              uuid primary key default gen_random_uuid(),
    created_at      timestamptz default now(),
    action          text not null,
    agent_name      text not null,
    asset_id        text,
    asset_type      text,
    health_status   text,
    request_ip_hash text,
    metadata        jsonb
);

create index if not exists audit_events_agent_idx on audit_events (agent_name);
create index if not exists audit_events_created_at_idx on audit_events (created_at desc);

-- Operational events (maintenance alerts, hub messages)
create table if not exists operational_events (
    id                    uuid primary key default gen_random_uuid(),
    event_type            text not null,
    created_at            timestamptz default now(),
    sender_agent          text,
    asset_id              text,
    asset_type            text,
    severity              text,
    payload               jsonb,
    published_destinations text[]
);

create index if not exists operational_events_type_idx on operational_events (event_type);
create index if not exists operational_events_created_at_idx on operational_events (created_at desc);

-- Row Level Security
alter table assets_history enable row level security;
alter table audit_events enable row level security;
alter table operational_events enable row level security;

-- Allow service role full access (used by backend only)
create policy "service_role_all_assets" on assets_history for all using (true);
create policy "service_role_all_audit" on audit_events for all using (true);
create policy "service_role_all_events" on operational_events for all using (true);
