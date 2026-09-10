# M4 — Maintenance & Asset Intelligence Agent

**Owner:** Member D (M4)
**Part of:** RailSense AI — 4-agent system (IT3041)

## Status: Phase 1 ✅ · Phase 2 ✅ · Phase 3 ✅ · Phase 4 ✅ · Phase 5 ✅

M4 is a FastAPI maintenance intelligence service with a browser dashboard, a trained
asset health model, NLP technician note extraction, a manual-based RAG system, Supabase
persistence, audit logging, Hub integration, and local fallbacks for offline demos.

## What's in this agent

| File | Purpose |
|---|---|
| `main.py` | FastAPI app — all endpoints, dashboard API, Hub receiver |
| `data/generate_dataset.py` | Generates `assets_history.csv` — 600 synthetic asset records |
| `data/assets_history.csv` | Generated dataset — feeds Phase 2 (ML) and dashboard |
| `hub_client.py` | Hub and Upstash adapters for `maintenance_alert` events |
| `supabase_store.py` | Supabase persistence and read adapters with local fallbacks |
| `ui/index.html` | Maintenance control-room dashboard (purple theme) at `/` |
| `ml/` | Health scoring model (GradientBoostingRegressor, 0–100 score) |
| `nlp/` | Technician note extraction and report summarization |
| `rag/` | Equipment manual retrieval — TF-IDF fallback + Supabase pgvector |
| `manuals/` | Five Sri Lanka Railways equipment manuals (RAG corpus) |
| `evaluation/` | ML, NLP, and RAG evaluation scripts and artifacts |
| `requirements.txt` | All Python dependencies |
| `.env.example` | Environment variable template |

## Run it

From the repository root:

```bash
pip install -r M4-maintenance-agent/requirements.txt
python -m uvicorn main:app --app-dir M4-maintenance-agent --reload --port 8002
```

Or from this directory:

```bash
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8002
```

Then:
- Dashboard: `http://localhost:8002/`
- Swagger UI: `http://localhost:8002/docs`
- Health check: `http://localhost:8002/health`

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/` | Maintenance dashboard frontend |
| POST | `/asset-health` | Predict asset health score + manual-grounded recommendation |
| GET | `/asset-status/{asset_id}` | Latest status record for a specific asset |
| POST | `/maintenance-report` | NLP extraction + summarization of technician report |
| GET | `/manual-search?q=...` | RAG search across equipment manuals |
| POST | `/hub/message` | Receive `maintenance_check` from the Agent Hub |
| GET | `/api/dashboard` | Aggregated dashboard data (metrics, events, RAG info) |
| GET | `/api/assets` | All assets with optional type/status filters |

## Phase 2 — ML Health Scoring Model

### Train / retrain

```bash
cd M4-maintenance-agent/ml && python train_health_model.py
```

The model is a `GradientBoostingRegressor` trained on `assets_history.csv`. It predicts
a continuous health score (0–100) from asset type, sensor readings, days since last service,
and fault count. Health status is derived from thresholds: ≥70 → GREEN, ≥40 → AMBER, <40 → RED.

### Expected metrics (600-row synthetic dataset, 80/20 split)

| Metric | Expected |
|---|---|
| MAE | ~3–5 points |
| RMSE | ~5–8 points |
| R² | ~0.85–0.92 |

## Phase 3 — NLP: Technician Note Extraction + Summarization

- `nlp/extract_notes.py`: keyword-based fault type detection, parts and actions extraction, measurements extraction. Optional LLM mode with `ANTHROPIC_API_KEY`.
- `nlp/summarize_report.py`: extractive frequency-based summarization. Optional LLM mode.

```bash
python M4-maintenance-agent/nlp/evaluate_nlp.py
```

## Phase 4 — RAG: Equipment Manual Retrieval

**This is the core RAG system for M4.**

Five equipment manuals cover the main asset types:

| Manual | Asset Type |
|---|---|
| `diesel_engine_manual.txt` | diesel_engine, electric_loco |
| `brake_system_manual.txt` | brake_system |
| `bogie_inspection_guide.txt` | bogie |
| `signal_equipment_manual.txt` | signal_unit, level_crossing |
| `track_maintenance_reference.txt` | track_section |

The retriever splits manuals by `## Section` headings and builds a TF-IDF index (offline
fallback) or Supabase pgvector index (cloud). The `/asset-health` endpoint automatically
cites relevant manual sections alongside the ML prediction.

### Run retrieval evaluation

```bash
python M4-maintenance-agent/evaluation/rag/evaluate_retrieval.py
```

### Embed manuals into Supabase pgvector (optional)

1. Run `rag/supabase_schema.sql` in the Supabase SQL editor.
2. Then:

```bash
python M4-maintenance-agent/rag/embed_manuals.py
```

## Phase 5 — Hub Integration, Supabase, Audit Log, Dashboard

- `hub_client.py`: registers with Hub, publishes `maintenance_alert` when asset health is RED
- `/hub/message`: accepts `maintenance_check` envelopes from Passenger Agent or Hub
- `supabase_store.py`: persists audit events and operational events; falls back to local JSONL
- `supabase_schema.sql`: creates `assets_history`, `audit_events`, `operational_events` tables
- Dashboard polls `/api/dashboard` every 30 seconds for live data

## Dataset

Generate or regenerate:

```bash
cd M4-maintenance-agent/data && python generate_dataset.py
```

600 records covering 8 asset types across 28 Sri Lanka Railways stations and 7 routes.
Columns: `record_id, asset_id, asset_type, station, route, last_service_date, days_since_service,
fault_type, fault_count_30d, health_score, health_status, technician_note, recommended_action`
plus asset-type-specific sensor columns (null where not applicable).

## Environment variables

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY` | Backend persistence |
| `SUPABASE_KEY` | pgvector retrieval |
| `UPSTASH_REDIS_URL`, `UPSTASH_REDIS_TOKEN` | Publish `maintenance_alert` events |
| `ANTHROPIC_API_KEY` | Optional LLM extraction, summarization, recommendation |
| `HUB_BASE_URL` | Agent Hub URL (default `http://localhost:8000`) |

## Project structure

```text
M4-maintenance-agent/
├── main.py                         FastAPI application and API routes
├── hub_client.py                   Hub and Upstash adapters
├── supabase_store.py               Supabase persistence/read adapters
├── supabase_schema.sql             All Supabase tables for M4
├── requirements.txt                Python dependencies
├── .env.example                    Environment variable template
├── ui/index.html                   Browser dashboard (purple theme)
├── data/
│   ├── assets_history.csv          Synthetic 600-row dataset
│   └── generate_dataset.py         Dataset generator
├── ml/
│   ├── train_health_model.py       Model training script
│   ├── predict.py                  Prediction wrapper (loaded by main.py)
│   └── health_model.pkl            Trained model artifact (after training)
├── nlp/
│   ├── extract_notes.py            Technician note extraction
│   ├── summarize_report.py         Report summarization
│   └── evaluate_nlp.py             NLP evaluation script
├── rag/
│   ├── manual_retriever.py         TF-IDF + pgvector retrieval
│   ├── embed_manuals.py            Embed manuals into Supabase
│   ├── supabase_schema.sql         pgvector table and RPC
│   └── recommendation.py          Grounded recommendation composer
├── manuals/
│   ├── diesel_engine_manual.txt
│   ├── brake_system_manual.txt
│   ├── bogie_inspection_guide.txt
│   ├── signal_equipment_manual.txt
│   └── track_maintenance_reference.txt
└── evaluation/
    ├── ml/health_model_metrics.json        (generated)
    ├── nlp/classification_metrics.json     (generated)
    ├── nlp/summarization_examples.json     (generated)
    ├── nlp/out_of_template_robustness_check.json (generated)
    └── rag/evaluate_retrieval.py           Retrieval evaluation script
```
