# RailSense AI - Supabase Implementation Checklist

This document tracks every Supabase task required to complete the cloud data layer for the five-phase RailSense Operations Agent.

Work through the sections one task at a time. Do not commit real Supabase keys, service-role keys, database passwords, or JWT secrets to Git.

## Target Architecture

Supabase will provide:

- PostgreSQL storage for the operations history dataset
- pgvector storage for historical incident embeddings
- RPC retrieval for grounded incident precedent
- Persistent audit records for predictions, incidents, Hub messages, and delay alerts
- Persistent operational events for the dashboard
- Optional Supabase Storage for exported evaluation reports or uploaded incident files

The local CSV and in-memory runtime state should remain available as an offline fallback for demos.

## Current Repository Assets

- Dataset: `M2-operations-agent/data/operations_history.csv`
- Existing vector schema: `M2-operations-agent/rag/supabase_schema.sql`
- Embedding uploader: `M2-operations-agent/rag/embed_documents.py`
- Retrieval adapter: `M2-operations-agent/rag/incident_retriever.py`
- Environment template: `M2-operations-agent/.env.example`
- Dashboard API: `M2-operations-agent/main.py`

## Phase A - Create And Secure The Supabase Project

- [ ] Create or select the shared Supabase project for the RailSense team.
- [ ] Record the project URL without placing it in source code.
- [ ] Create a restricted application key for normal API access.
- [ ] Keep the service-role key private and use it only for controlled ingestion scripts.
- [ ] Confirm the project region and document it for the team.
- [ ] Enable database backups or confirm the available free-tier recovery policy.
- [ ] Confirm that the project has the pgvector extension available.
- [ ] Add the local `.env` file to `.gitignore` if it is not already ignored.
- [ ] Populate local environment variables from `.env.example`.
- [ ] Verify that no secret values appear in Git history, README files, screenshots, or logs.

Required environment variables:

```text
SUPABASE_URL=
SUPABASE_KEY=
DATABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
```

`SUPABASE_SERVICE_ROLE_KEY` is optional for application runtime and should only be used by the ingestion command when required.

## Phase B - Create The Operations History Table

- [ ] Create an `operations_history` table in Supabase.
- [ ] Preserve the dataset fields:
  - `record_id`
  - `route`
  - `station`
  - `train_id`
  - `scheduled_time`
  - `actual_time`
  - `weather`
  - `day_type`
  - `incident_type`
  - `incident_note`
  - `delay_minutes`
- [ ] Use a UUID or text-compatible primary key for `record_id`.
- [ ] Use timestamp types for `scheduled_time` and `actual_time`.
- [ ] Use numeric storage for `delay_minutes`.
- [ ] Add indexes for `route`, `station`, `scheduled_time`, and `incident_type`.
- [ ] Add a uniqueness rule on `record_id` so ingestion can be safely repeated.
- [ ] Add basic database checks for non-negative delay values where appropriate.
- [ ] Decide whether slightly early trains, represented by negative delays, are allowed.
- [ ] Add table and column comments describing the synthetic dataset and its provenance.

## Phase C - Import The Historical Dataset

- [ ] Choose one ingestion method:
  - Supabase Table Editor for a small one-time import
  - Python `supabase` client for repeatable ingestion
  - PostgreSQL `COPY` through a controlled database connection
- [ ] Build or add an idempotent import script.
- [ ] Convert ISO timestamp strings into database timestamps.
- [ ] Convert numeric fields before insertion.
- [ ] Use upsert on `record_id` instead of blind inserts.
- [ ] Import all 3,000 records.
- [ ] Verify the database row count is exactly 3,000.
- [ ] Compare route counts between CSV and Supabase.
- [ ] Compare incident-type counts between CSV and Supabase.
- [ ] Compare minimum, maximum, mean, and standard deviation of `delay_minutes`.
- [ ] Record the import date and dataset version.

## Phase D - Create The pgvector Incident Table

The starter schema is in `M2-operations-agent/rag/supabase_schema.sql`.

- [ ] Run `create extension if not exists vector`.
- [ ] Create the `incident_embeddings` table.
- [ ] Confirm the embedding dimension is 384 for `all-MiniLM-L6-v2`.
- [ ] Preserve the source incident metadata beside each vector.
- [ ] Add a unique primary key on `record_id`.
- [ ] Create the IVFFLAT or HNSW vector index after data loading, if supported by the project tier.
- [ ] Confirm cosine distance is used consistently by the index and RPC.
- [ ] Create the `match_incidents` RPC.
- [ ] Cap the RPC result count to five records.
- [ ] Add optional route, station, and incident-type filters if the final dashboard needs filtered retrieval.
- [ ] Test the RPC with a known 384-dimensional vector.

## Phase E - Generate And Upload Embeddings

- [ ] Confirm the local `sentence-transformers` dependency is installed.
- [ ] Confirm the model is `all-MiniLM-L6-v2`.
- [ ] Generate embeddings only for rows with non-empty `incident_note` values.
- [ ] Normalize embeddings before upload.
- [ ] Upload in batches using `M2-operations-agent/rag/embed_documents.py`.
- [ ] Use upsert so the command can safely be rerun.
- [ ] Do not log embedding values or Supabase credentials.
- [ ] Verify the number of vector rows matches the number of non-empty incident notes.
- [ ] Verify a sample record contains route, station, incident type, delay, note, and vector.
- [ ] Record the embedding model version and upload date.
- [ ] Confirm the generated local cache is either intentionally retained or removed according to the team storage policy.

Expected command:

```powershell
python M2-operations-agent/rag/embed_documents.py
```

## Phase F - Switch And Verify Retrieval

- [ ] Set `SUPABASE_URL` and `SUPABASE_KEY` in the local environment.
- [ ] Run a known incident query through `incident_retriever.py`.
- [ ] Confirm the response method is `supabase_pgvector`.
- [ ] Confirm the response includes the expected incident type.
- [ ] Confirm top-k is limited to three for normal prediction explanations.
- [ ] Verify route and station context are included in the query or filters.
- [ ] Verify retrieval gracefully falls back to local TF-IDF when Supabase is unavailable.
- [ ] Run `evaluation/rag/evaluate_retrieval.py` against the configured backend.
- [ ] Save the cloud-backend retrieval metrics separately from the local TF-IDF metrics.
- [ ] Compare cloud and local P@1, P@3, and P@5.
- [ ] Test a paraphrased incident query and document the result honestly.

## Phase G - Persistent Audit Log

Create an `audit_events` table for durable security and operational records.

Recommended fields:

- `id` UUID primary key
- `created_at` timestamptz
- `action` text
- `agent_name` text
- `sender_agent` text nullable
- `receiver_agent` text nullable
- `route` text nullable
- `train_id` text nullable
- `predicted_delay_minutes` numeric nullable
- `model_version` text nullable
- `classified_type` text nullable
- `request_ip_hash` text nullable
- `metadata` jsonb

Tasks:

- [ ] Create the table and indexes.
- [ ] Never store raw auth tokens in audit records.
- [ ] Hash or omit client IP addresses according to the project privacy policy.
- [ ] Add retention guidance for old records.
- [ ] Write prediction events to Supabase after successful validation.
- [ ] Write incident-report events to Supabase.
- [ ] Write inbound Hub message events to Supabase.
- [ ] Keep local JSONL logging as an offline fallback.
- [ ] Verify failed Supabase writes do not break the prediction response.
- [ ] Add a dashboard count of persisted audit events.

## Phase H - Persistent Delay Alerts And Dashboard Events

Create an `operational_events` table for delay alerts and other agent events.

Recommended fields:

- `id` UUID primary key
- `event_type` text
- `created_at` timestamptz
- `sender_agent` text
- `route` text nullable
- `train_id` text nullable
- `severity` text
- `payload` jsonb
- `published_destinations` text[]

Tasks:

- [ ] Create the table and indexes on `event_type`, `created_at`, and `route`.
- [ ] Persist every threshold-crossing `delay_alert`.
- [ ] Store whether delivery reached the Hub or Upstash Redis.
- [ ] Store delivery errors without exposing credentials.
- [ ] Add a query for recent alerts used by `/api/events`.
- [ ] Add a query for active alerts used by `/api/dashboard`.
- [ ] Add a way to acknowledge or close an alert if the dashboard requires it.
- [ ] Confirm the dashboard still works when the cloud database is unavailable.

## Phase I - Dashboard Data Queries

Move dashboard aggregates from CSV-only calculations to Supabase queries when cloud data is configured.

- [ ] Network average delay.
- [ ] On-time percentage.
- [ ] Route-level average, maximum, and incident rate.
- [ ] Hourly delay pressure.
- [ ] Incident-type distribution.
- [ ] Recent incident feed.
- [ ] Recent delay alerts.
- [ ] Feature importance and evaluation metrics remain file-backed artifacts unless a metrics table is preferred.
- [ ] Add date-range filters.
- [ ] Add route filters.
- [ ] Add pagination for incident and event feeds.
- [ ] Add a generated-at timestamp and source indicator (`supabase` or `local_csv`).
- [ ] Verify all dashboard values match direct SQL checks.

## Phase J - Row Level Security And API Safety

- [ ] Enable Row Level Security on all application tables.
- [ ] Decide which tables are read-only to the dashboard.
- [ ] Create least-privilege policies for authenticated application access.
- [ ] Prevent anonymous writes to operations history, audit events, and alerts.
- [ ] Keep service-role access out of browser code.
- [ ] Never expose `SUPABASE_SERVICE_ROLE_KEY` to the frontend.
- [ ] Validate and constrain all values before database insertion.
- [ ] Add maximum page sizes to dashboard queries.
- [ ] Add query timeouts and error handling.
- [ ] Review whether raw incident text contains personal or sensitive information.

## Phase K - Supabase Storage, If Required

Use Supabase Storage only if the project needs durable files.

- [ ] Decide whether evaluation JSON files should remain in Git or be uploaded.
- [ ] Create a private bucket for exports or incident attachments.
- [ ] Add file type and file size limits.
- [ ] Store only object paths in database rows.
- [ ] Generate short-lived signed URLs for private files.
- [ ] Do not make incident attachments publicly readable by default.
- [ ] Add malware/content validation if uploads are introduced.

## Phase L - Final Verification Checklist

- [ ] Supabase project is reachable from the operations service.
- [ ] Operations history row count matches the source dataset.
- [ ] Incident embedding row count is correct.
- [ ] `match_incidents` returns relevant results.
- [ ] `/predict-delay` reports `supabase_pgvector` when configured.
- [ ] `/predict-delay` still works with Supabase disabled.
- [ ] Audit records persist after service restart.
- [ ] Delay alerts persist after service restart.
- [ ] Dashboard shows cloud-backed data and identifies its source.
- [ ] RLS policies reject unauthorized writes.
- [ ] No secrets are present in Git, frontend assets, logs, or screenshots.
- [ ] Cloud retrieval metrics are generated and saved.
- [ ] A full Passenger -> Hub -> Operations -> alert -> dashboard demonstration succeeds.

## Suggested Execution Order

1. Create the Supabase project and configure local environment variables.
2. Create and verify the operations history table.
3. Import and compare the 3,000 historical records.
4. Create the pgvector table, index, and RPC.
5. Upload and count incident embeddings.
6. Switch retrieval to Supabase and run evaluation.
7. Add persistent audit events.
8. Add persistent operational events and alerts.
9. Move dashboard aggregates to Supabase with local fallback.
10. Apply RLS and run the final security checks.
