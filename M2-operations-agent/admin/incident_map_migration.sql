-- Incident map — additive migration for incident_reports.
-- Run once in the Supabase SQL editor. Safe to re-run.
--
-- review_status gains the value 'verified', set ONLY by
-- POST /incidents/{id}/approve (admin capability m2.incidents.review).
-- The incident map feed (GET /api/incidents/map-feed) shows verified rows only.
-- Until this migration is applied M2 still works: approvals are written
-- without verified_at and the feed falls back to reviewed_at.

alter table incident_reports add column if not exists verified_at timestamptz;

create index if not exists idx_incident_reports_verified
    on incident_reports (verified_at desc)
    where review_status = 'verified';

comment on column incident_reports.review_status is
    'pending | corrected | approved (legacy) | verified | rejected';
