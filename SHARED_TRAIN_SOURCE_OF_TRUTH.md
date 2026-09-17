# Shared Train Source of Truth

Part 1 establishes the shared Supabase train registry without changing any
agent runtime behavior.

## Deliverables

- [supabase_shared_trains.sql](supabase_shared_trains.sql): additive migration
  for the existing M3 `trains` and `train_schedules` tables.
- [scripts/seed_shared_trains.py](scripts/seed_shared_trains.py): idempotent
  Supabase upsert and discovered-ID report generator.
- `shared_train_ids_report.json`: generated complete ID inventory. Regenerate it
  whenever source data changes.

## Canonical model

```text
trains
  id                         internal PostgreSQL primary key
  train_id                   unique cross-agent identity
  train_name
  origin_station
  destination_station
  route
  train_type
  active                    existing M3 active flag
  maintenance_status
  class_capacities           JSONB class -> capacity snapshot
  current_class_availability JSONB class -> availability snapshot
  metadata                   JSONB source/provenance details
  created_at
  updated_at
       |
       +-- train_schedules
             train_id         FK to trains.id
             from_station
             to_station
             travel_date      existing M3 date-specific field
             departure_time
             arrival_time
             first_class_capacity
             second_class_capacity
             service_status
             created_at
             updated_at
```

`train_id` is the only cross-agent identity. M2 `operations_history` and M4
`assets_history` remain specialized historical/telemetry tables. M4 asset IDs
such as `DE-1001`, `BG-1001`, and `SG-1001` are not trains and are excluded.

## Discovered source inventory

- M1: `PM-4082` in the booking/delay contract and NER examples. The FAQ
  schedule document also has unprefixed timetable numbers such as `1005`,
  `1010`, `1015`, and `1020`; these are reference numbers, not canonical IDs.
- M2: 3,000 operation rows and 2,915 distinct historical train IDs, plus
  dashboard identities `PM-8056`, `IC-1001`, and `DM-8055`.
- M3: production/test identities `PM-4082`, `INACT-9999`, `PM-5000`, and
  `EXP-OVERLAP`; date-specific schedules remain in `train_schedules`.
- M4: train-name to locomotive mapping in `rag/chatbot.py`. Values such as
  `DE-1001` are locomotive asset IDs; the train numbers in that mapping are
  not promoted to `train_id` until a future alias/identity decision is made.

The current dry-run seed inventory is **2,922 canonical records**: 2,915 M2
historical identities plus seven explicit M2/M3 registry or test identities.
The full sorted list is written to `shared_train_ids_report.json` by the seed
script.

## Conflicts preserved

1. M3 defines `PM-4082` as **Intercity Express**, Colombo to Kandy, with a
   2026-12-03 schedule and 40/120 first/second-class capacities. This is the
   canonical booking value.
2. M1's FAQ uses SLR-style unprefixed numbers such as `1005` and `1015`, while
   M4 maps names to different locomotive numbers such as `1015` and `1083`.
   These are not silently merged with `PM-4082`.
3. M2 rows are historical observations, not current timetable services. Their
   records are seeded as identity/provenance rows only; the original
   `operations_history` rows are preserved unchanged.
4. M4 maintenance records remain keyed by `asset_id` and are not copied into
   the train registry.

## Apply and seed

1. Run `supabase_shared_trains.sql` in the Supabase SQL editor.
2. Verify the migration created the additive columns and indexes.
3. Run a local dry run:

   ```powershell
   python scripts/seed_shared_trains.py --dry-run
   ```

4. Run the idempotent Supabase seed using the root `.env`:

   ```powershell
   python scripts/seed_shared_trains.py
   ```

The script requires `SUPABASE_URL` and `SUPABASE_SECRET_KEY` (or
`SUPABASE_SERVICE_ROLE_KEY`). It does not print credentials. Re-running it
updates the same `train_id` rows rather than creating duplicates.
