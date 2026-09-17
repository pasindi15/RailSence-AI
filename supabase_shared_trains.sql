-- RailSense AI shared train source of truth
-- Part 1: additive migration only. No application behavior is changed here.
-- Run this file in the existing Supabase SQL editor before running
-- scripts/seed_shared_trains.py.

-- M3 already owns these tables. Extend them instead of creating duplicate
-- train identity or schedule tables.

ALTER TABLE public.trains
    ADD COLUMN IF NOT EXISTS origin_station text,
    ADD COLUMN IF NOT EXISTS destination_station text,
    ADD COLUMN IF NOT EXISTS route text,
    ADD COLUMN IF NOT EXISTS train_type text,
    ADD COLUMN IF NOT EXISTS maintenance_status text NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS class_capacities jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS current_class_availability jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

-- The existing M3 `active` column is the canonical active-status field.
-- Keep it for ORM/application compatibility and make its index explicit.
CREATE INDEX IF NOT EXISTS trains_origin_destination_idx
    ON public.trains (origin_station, destination_station);
CREATE INDEX IF NOT EXISTS trains_active_idx
    ON public.trains (active);
CREATE INDEX IF NOT EXISTS trains_route_idx
    ON public.trains (route);
CREATE INDEX IF NOT EXISTS trains_updated_at_idx
    ON public.trains (updated_at DESC);

ALTER TABLE public.train_schedules
    ADD COLUMN IF NOT EXISTS service_status text NOT NULL DEFAULT 'SCHEDULED',
    ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS train_schedules_route_date_idx
    ON public.train_schedules (from_station, to_station, travel_date);
CREATE INDEX IF NOT EXISTS train_schedules_service_status_idx
    ON public.train_schedules (service_status);

-- Prevent duplicate date-specific services while preserving the existing
-- integer foreign key from train_schedules.train_id to trains.id.
CREATE UNIQUE INDEX IF NOT EXISTS train_schedules_identity_idx
    ON public.train_schedules (train_id, travel_date, from_station, to_station);

-- Keep updated_at current for future writes from any agent.
CREATE OR REPLACE FUNCTION public.set_train_source_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trains_set_updated_at ON public.trains;
CREATE TRIGGER trains_set_updated_at
BEFORE UPDATE ON public.trains
FOR EACH ROW EXECUTE FUNCTION public.set_train_source_updated_at();

DROP TRIGGER IF EXISTS train_schedules_set_updated_at ON public.train_schedules;
CREATE TRIGGER train_schedules_set_updated_at
BEFORE UPDATE ON public.train_schedules
FOR EACH ROW EXECUTE FUNCTION public.set_train_source_updated_at();

COMMENT ON TABLE public.trains IS
    'Canonical train identity registry. train_id is the cross-agent unique identity.';
COMMENT ON COLUMN public.trains.train_id IS
    'Canonical cross-agent train identity. Never reuse this value for an asset ID.';
COMMENT ON COLUMN public.trains.class_capacities IS
    'JSON object keyed by supported booking class, for example {"First Class": 40}.';
COMMENT ON COLUMN public.trains.current_class_availability IS
    'Current availability snapshot; booking remains authoritative for live seat counts.';
COMMENT ON TABLE public.train_schedules IS
    'Date-specific scheduled services linked to the canonical trains registry.';
