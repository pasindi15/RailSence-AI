# M2 — Operations & Delay-Prediction Agent

**Owner:** Member B (M2)
**Part of:** RailSense AI — 4-agent system (IT3041)

## Status: Phase 1 ✅ · Phase 2 ✅ · Phase 3 ✅ · Phase 4 ✅ · Phase 5 ✅

M2 is a runnable FastAPI operations service with a browser dashboard, stable
agent-to-agent APIs, a trained delay model, incident NLP, retrieval-grounded
explanations, Supabase persistence, audit logging, rate limiting, and optional
Hub/Upstash integrations. It remains demoable without cloud services through
the local CSV, TF-IDF, JSONL, and in-memory fallbacks described below.

## What's in this phase

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, dashboard API, prediction, incident, and Hub endpoints |
| `data/generate_dataset.py` | Generates `operations_history.csv` — 3000 synthetic rows (route, station, weather, day_type, incident_type, delay_minutes, incident_note) |
| `data/operations_history.csv` | The generated dataset — feeds Phase 2 (ML) and Phase 4 (RAG corpus) |
| `hub_client.py` | Best-effort Hub and Upstash adapters |
| `supabase_store.py` | Supabase persistence and read adapters |
| `ui/index.html` | Operations control-center frontend served at `/` with Home plus six live screens |
| `ml/`, `nlp/`, `rag/`, `evaluation/` | Model, NLP, retrieval, and evaluation code/artifacts |
| `requirements.txt` | All dependencies needed across all 5 phases |
| `.env.example` | Required environment variables (Supabase, Upstash, JWT, Anthropic key) |

## Run it

From the repository root:

```bash
pip install -r M2-operations-agent/requirements.txt
python -m uvicorn main:app --app-dir M2-operations-agent --reload --port 8001
```

Or, from this directory:

```bash
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8001
```

Then visit `http://localhost:8001/docs` for interactive Swagger UI.

The operations control room is available at `http://localhost:8001/`. It
displays real route and hourly delay aggregates, incident mix, model and NLP
evaluation evidence, live event state, and an auto-refreshed incident feed.
The operator drawer can run audited predictions and classify incidents.

Phase 5 APIs include `/api/dashboard`, `/api/operations`, `/api/events`,
`/hub/message`, and the data-backed `/route-status/{route_id}`. Configure `HUB_BASE_URL` and the
Upstash variables for external agent registration and `delay_alert` delivery;
the local dashboard remains fully demoable without cloud services.

### Run the frontend and backend

M2 does not have a separate React or npm frontend. FastAPI serves
`ui/index.html` at `/` and the page fetches its live data from
`/api/dashboard`, so one command runs both parts:

```powershell
python -m uvicorn main:app --app-dir M2-operations-agent --reload --port 8001
```

Open `http://127.0.0.1:8001/` for the dashboard, `/docs` for Swagger UI, and
`/health` for the liveness check. The dashboard renders network delay,
on-time performance, alerts, audit count, hourly pressure, route statistics,
incident mix, model/NLP metrics, and the incident feed from the API response.

## Endpoints (Phase 1 contracts — stable going forward)

- `GET /health` — liveness check
- `GET /` — serves the operations control-room frontend.
- `GET /api/dashboard` — returns dashboard aggregates, evaluation metrics,
  feature importance, incident feed, events, and Hub status.
- `GET /api/events` — returns recent events held by the running process.
- `GET /api/operations` — returns trains, incidents, risk zones, level
  crossings, alerts, and dispatch actions for the six operational screens.
- `POST/PATCH/DELETE /api/operations/{entity_type}[/{entity_id}]` — CRUD for
  those operational entities. Supabase is used when configured; otherwise the
  seeded Sri Lankan railway demo records provide a complete local fallback.
- `POST /predict-delay` — predicts delay, retrieves similar incidents, writes
  an audit record, and publishes a `delay_alert` when the threshold is met.
- `GET /route-status/{route_id}` — returns live aggregation for an exact route.
- `POST /incident-report` — sanitizes, summarizes, classifies, and audits a
  staff report. Control characters, HTML markup, and invalid lengths are
  rejected by Pydantic validation.
- `POST /hub/message` — receives a Hub `delay_check` and returns a
  `delay_check_response`.

The complete request and response schemas are available at `/docs`.

## Data sources and fallback behavior

The dashboard is data-backed, but different cards use different sources:

| Dashboard data | Primary source | Local fallback |
|---|---|---|
| Historical trips, routes, delays, hourly aggregates, incident mix | Supabase `operations_history` | `data/operations_history.csv` |
| Audit count | Supabase `audit_events` | `data/audit_log.jsonl` |
| Operational events and alert count | Supabase `operational_events` | In-memory events for the current process |
| Live trains, incidents, risk zones, crossings, alerts, dispatch actions | Supabase `operation_entities` | Seeded local demo records |
| Model and NLP cards | Local JSON evaluation artifacts | Empty/zero values if artifacts are missing |
| Incident feed | Live in-memory reports plus local historical records | Local historical records |
| Headings, labels, and dropdown options | `ui/index.html` | Not database content |

The frontend does not connect directly to Supabase. It calls the FastAPI API,
and the backend chooses Supabase or a local fallback. A successful local demo
therefore does not by itself prove that Supabase is configured.

## Supabase setup

1. Create a repository-root `.env` file from `.env.example`.
2. Set `SUPABASE_URL`.
3. Set `SUPABASE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY` for backend reads
   and writes.
4. Run `supabase_phase5_schema.sql` in the Supabase SQL editor.
5. Import the 3,000 historical rows:

```powershell
python M2-operations-agent/data/import_to_supabase.py
```

The schema creates `operations_history`, `incident_embeddings`,
`audit_events`, `operational_events`, and the extensible `operation_entities`
table, plus the `match_incidents` pgvector
function. Cloud failures are intentionally non-fatal so the local dashboard
continues to work.

Verify connectivity without printing credentials:

```powershell
python -c "import sys; sys.path.insert(0, 'M2-operations-agent'); import supabase_store; c=supabase_store.get_client(); print('client:', bool(c)); print('history:', len(supabase_store.fetch_history() or []))"
```

## Environment variables

The backend loads a repository-root `.env` when started directly. Important
variables are:

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY` | Backend persistence |
| `SUPABASE_PUBLISHABLE_KEY` or `SUPABASE_KEY` | pgvector retrieval client |
| `UPSTASH_REDIS_URL`, `UPSTASH_REDIS_TOKEN` | Publish `delay_alert` events |
| `ANTHROPIC_API_KEY` | Optional LLM explanations/classification |
| `HUB_BASE_URL` | Shared agent Hub; defaults to `http://localhost:8000` |
| `HUB_AUTH_TOKEN` or `JWT_TOKEN` | Hub authorization |
| `OPERATIONS_AGENT_URL` | Callback URL used during Hub registration |

Do not commit `.env` or secret keys. The checked-in `.env.example` is only a
template.

## Dataset

Regenerate with:

```bash
cd data && python generate_dataset.py
```

Columns: `record_id, route, station, train_id, scheduled_time, actual_time,
weather, day_type, incident_type, incident_note, delay_minutes`

Covers 7 Sri Lanka Railways-style routes, weighted peak-hour departures,
weather-correlated incident likelihood, and free-text incident notes
templated per incident type (used later for NLP summarization and RAG
embedding).

## Phase 2 — Delay Prediction Model

| File | Purpose |
|---|---|
| `ml/train_delay_model.py` | Trains a `GradientBoostingRegressor` on `operations_history.csv`, saves `delay_model.pkl` + `feature_importances.json`, writes metrics to `evaluation/ml/delay_model_metrics.json` |
| `ml/predict.py` | Loads the trained model once and exposes `predict_delay()`, used directly by `main.py` |
| `ml/delay_model.pkl` | The trained model artifact (regenerate anytime with the command below) |
| `ml/feature_importances.json` | Top 20 features ranked by importance |
| `evaluation/ml/delay_model_metrics.json` | Held-out test MAE / RMSE / R² |

### Train / retrain

From the repository root, Bash and PowerShell commands are:

```bash
cd ml && python train_delay_model.py
```

```powershell
Set-Location M2-operations-agent\ml; python train_delay_model.py
```

PowerShell 5.1 does not support `&&`; use `;` as the command separator.

### Current held-out test metrics (3000-row synthetic dataset, 80/20 split)

| Metric | Value |
|---|---|
| MAE | ~2.24 minutes |
| RMSE | ~2.88 minutes |
| R² | ~0.87 |

Top contributing features: whether an incident occurred at all
(`incident_type_none` dominates, as expected — no incident vs. any incident
is the single biggest swing factor), followed by incident sub-type
(mechanical, track obstruction) and weather (clear vs. heavy rain).

**Note:** these are real metrics from the synthetic dataset generated in
Phase 1, not invented numbers — but they will need to be re-run and
re-reported once the dataset is finalized for submission, per the
project's evaluation-framework rule against invented scores.

### `/predict-delay` now returns real model output

```json
{
  "route": "Colombo Fort - Kandy",
  "train_id": "PM-4082",
  "station": "Kandy",
  "incident_type": "mechanical",
  "predicted_delay_minutes": 7.1,
  "confidence": "medium",
  "explanation": "Expect ~7.1 min delay ... strongest learned signals: incident type none, incident type mechanical, weather clear ...",
  "top_contributing_features": [...],
  "similar_past_incidents": [],
  "model_version": "phase2-gbr-v1"
}
```

`station` and `incident_type` are optional for backwards compatibility. When
provided, they are passed to the Phase 2 model as additional categorical
features; omitted values use the model wrapper's `unknown` / `none` defaults.

If `delay_model.pkl` hasn't been trained yet, the endpoint automatically
falls back to the labelled Phase 1 heuristic instead of failing — so the
service is always runnable.

## Phase 4 — Retrieval, Grounding & Explanation

| File | Purpose |
|---|---|
| `rag/incident_retriever.py` | Retrieves the top 3 historical incidents using Supabase pgvector or local TF-IDF fallback |
| `rag/embed_documents.py` | Embeds incident notes with `all-MiniLM-L6-v2` and uploads them to Supabase |
| `rag/supabase_schema.sql` | Creates the pgvector table, index, and `match_incidents` RPC |
| `rag/explanation.py` | Composes a grounded template or optional Anthropic explanation |
| `evaluation/rag/evaluate_retrieval.py` | Measures P@1/P@3/P@5 and runs a paraphrased-query stress test |

`/predict-delay` now returns `similar_past_incidents`, `retrieval_method`, and
`explanation_method`. Without cloud variables it is fully demoable offline
using the CSV corpus and TF-IDF. With `SUPABASE_URL` and `SUPABASE_KEY`, the
retriever uses the pgvector RPC. With `ANTHROPIC_API_KEY`, it also asks Claude
to compose the final explanation from only the prediction, model signals,
and retrieved evidence.

### Retrieval evaluation evidence

Run the evaluation from the repository root:

```powershell
python M2-operations-agent/evaluation/rag/evaluate_retrieval.py
```

The generated-template evaluation uses same-`incident_type` agreement as an
explicit relevance proxy. On 150 held-out incident-note queries, the local
TF-IDF backend measured:

| Metric | Result |
|---|---:|
| Precision@1 | 1.0000 |
| Precision@3 | 1.0000 |
| Precision@5 | 1.0000 |

The same command evaluates six hand-written paraphrases outside the dataset
templates. Top-1 accuracy was **0.6667** and top-3 recall was **0.6667**.
This is a small stress test, not a representative labelled benchmark; the
gap shows that lexical retrieval can miss unfamiliar phrasing.

Results are written to:

- `evaluation/rag/retrieval_metrics.json`
- `evaluation/rag/paraphrased_query_robustness.json`

To enable Supabase retrieval, run `rag/supabase_schema.sql` in the Supabase
SQL editor, then execute:

```bash
python M2-operations-agent/rag/embed_documents.py
```

## Phase 3 — Incident Summarization & Classification (NLP)

| File | Purpose |
|---|---|
| `nlp/classify_incident.py` | Rule-based keyword classifier (default) + optional LLM zero-shot mode if `ANTHROPIC_API_KEY` is set |
| `nlp/summarize_incident.py` | Extractive, frequency-scored summarizer (default) + optional LLM mode |
| `nlp/evaluate_nlp.py` | Evaluates the classifier against real ground-truth `incident_type` labels in the dataset; dumps summarization examples for review |
| `evaluation/nlp/classification_metrics.json` | Precision/recall/F1 per category, macro avg |
| `evaluation/nlp/summarization_examples.json` | Sample raw text → summary pairs, including a synthetic multi-sentence log |
| `evaluation/nlp/out_of_template_robustness_check.json` | Honest stress-test on paraphrased text (see below) |

### How classification works

Keyword/phrase matching against the six categories used in the dataset
(`signal_fault`, `mechanical`, `weather`, `track_obstruction`, `staffing`,
`other`). No API cost, deterministic, always available. An optional LLM
zero-shot path exists in the same file and activates automatically if
`ANTHROPIC_API_KEY` is set — not the default, since the rule-based baseline
is fast, free, and (on this dataset) very accurate.

### How summarization works

Extractive: splits text into sentences, scores each by word frequency
(minus a small stopword list), and keeps the top 1–2 highest-scoring
sentences in their original order. Short incident notes (already 1
sentence, by dataset design) pass through unchanged; longer multi-sentence
staff logs actually get condensed. Same LLM-upgrade pattern as
classification.

### Evaluation results — read both numbers together

**On the dataset's own templated incident notes** (400 samples, stratified
across all 5 non-"none" incident types):

| Metric | Value |
|---|---|
| Accuracy | 100% |
| Macro F1 | 1.00 |

**On paraphrased text outside the training templates** (6 hand-written
examples simulating what a real staff member might actually type):

| Metric | Value |
|---|---|
| Accuracy | 33% (2/6) |

**Why report both:** the 100% number is real, but it's inflated — the
synthetic dataset's incident notes were generated from templates that
share vocabulary with the keyword list, so this measures "does the
classifier recognize its own dictionary" more than "does it understand
free text." The 33% number on paraphrased input is the honest signal: this
baseline is a strong, demoable placeholder, but it will miss incident
reports phrased in unexpected ways once real staff write them. This is the
clearest limitation to raise in the viva, and it directly motivates the
optional LLM-classification path already built into `classify_incident.py`
as the natural upgrade.

### `/incident-report` now returns real NLP output

```json
{
  "incident_id": "...",
  "train_id": "PM-4082",
  "station": "Peradeniya",
  "summary": "Signal failure reported near Peradeniya, trains held for 12 minutes while technicians reset the interlocking system.",
  "classified_type": "signal_fault",
  "nlp_method": "rule_based",
  "received_at": "..."
}
```

Input sanitization runs in the Pydantic request model before either NLP
function is called. It enforces field length limits and rejects control
characters or any HTML markup after checking it with `bleach`, returning a
422 for malicious input.

## Hub and event integration

At startup, M2 attempts to register with `HUB_BASE_URL`. If the Hub is not
running, startup continues and the dashboard reports the offline fallback.
Predictions over five minutes create a `delay_alert` event. The event is sent
to Upstash Redis and/or the Hub when configured, then persisted to
`operational_events` when Supabase is available.

The `/hub/message` endpoint currently accepts the `delay_check` intent. It
validates the embedded prediction payload, runs the same prediction pipeline
as the dashboard, and returns a `delay_check_response` envelope.

## Evaluation and maintenance commands

Regenerate the deterministic synthetic dataset:

```powershell
Set-Location M2-operations-agent\data; python generate_dataset.py
```

Retrain the delay model:

```powershell
Set-Location M2-operations-agent\ml; python train_delay_model.py
```

Run NLP evaluation:

```powershell
python M2-operations-agent/nlp/evaluate_nlp.py
```

Run retrieval evaluation:

```powershell
python M2-operations-agent/evaluation/rag/evaluate_retrieval.py
```

Embed incident notes into Supabase pgvector after applying the schema:

```powershell
python M2-operations-agent/rag/embed_documents.py
```

The evaluation commands update JSON artifacts under `evaluation/`. Metrics
shown in the dashboard are therefore local evidence files, not live database
queries.

## Known limitations

- The dataset is synthetic and Sri Lanka Railways-flavoured; it is not a live
  railway telemetry feed.
- The default incident classifier is deterministic keyword matching. Its
  templated-data accuracy is high, but paraphrased-text accuracy is lower.
- Supabase retrieval requires the pgvector schema, embeddings, and a usable
  publishable key; otherwise retrieval uses local TF-IDF.
- The incident feed combines historical local records with live reports, so
  not every feed item is a row read from Supabase.
- The Hub and Upstash integrations are optional best-effort integrations.
- In-memory events and reports are lost when the process restarts; persisted
  Supabase audit and event rows are retained when cloud configuration works.

## Project structure

```text
M2-operations-agent/
|-- main.py                         FastAPI application and API routes
|-- hub_client.py                   Hub and Upstash adapters
|-- supabase_store.py               Supabase persistence/read adapters
|-- requirements.txt                Python dependencies
|-- .env.example                    Environment variable template
|-- ui/index.html                   Browser dashboard
|-- data/operations_history.csv     Synthetic operations corpus
|-- data/generate_dataset.py        Dataset generator
|-- data/import_to_supabase.py      Supabase history importer
|-- ml/                             Delay model and prediction wrapper
|-- nlp/                            Incident classification and summarization
|-- rag/                            Retrieval, embeddings, and explanations
|-- evaluation/                     ML, NLP, and RAG evidence JSON files
|-- supabase_phase5_schema.sql      Supabase tables, policies, and indexes
```
