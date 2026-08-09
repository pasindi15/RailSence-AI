# M2 — Operations & Delay-Prediction Agent

**Owner:** Member B (M2)
**Part of:** RailSense AI — 4-agent system (IT3041)

## Status: Phase 1 ✅ · Phase 2 ✅ · Phase 3 ✅ · Phase 4 ✅ · Phase 5 ✅

Phase 1 delivers a runnable, standalone FastAPI service with a stable API
contract and a realistic synthetic dataset, so later phases (ML, NLP, RAG,
Hub integration) can be built and demoed incrementally without ever
breaking the endpoints other agents will integrate against.

## What's in this phase

| File | Purpose |
|---|---|
| `main.py` | FastAPI app — `/health`, `/predict-delay`, `/route-status/{route_id}`, `/incident-report` |
| `data/generate_dataset.py` | Generates `operations_history.csv` — 3000 synthetic rows (route, station, weather, day_type, incident_type, delay_minutes, incident_note) |
| `data/operations_history.csv` | The generated dataset — feeds Phase 2 (ML) and Phase 4 (RAG corpus) |
| `hub_client.py` | Stub for Phase 5 Hub integration (register, send, publish `delay_alert`) |
| `ml/`, `nlp/`, `rag/`, `evaluation/` | Empty scaffolds for Phases 2–5 |
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

Phase 5 APIs include `/api/dashboard`, `/api/events`, `/hub/message`, and the
data-backed `/route-status/{route_id}`. Configure `HUB_BASE_URL` and the
Upstash variables for external agent registration and `delay_alert` delivery;
the local dashboard remains fully demoable without cloud services.

## Endpoints (Phase 1 contracts — stable going forward)

- `GET /health` — liveness check
- `POST /predict-delay` — currently returns a **placeholder heuristic**
  (weather/day-type based), clearly labelled `model_version: "phase1-heuristic-v0"`.
  Phase 2 swaps this for the trained ML model; Phase 4 adds the LLM
  explanation + retrieved similar incidents.
- `GET /route-status/{route_id}` — currently returns a static placeholder.
  Phase 5 backs this with live aggregation.
- `POST /incident-report` — currently echoes a naive summary with
  `classified_type: "unclassified"`. Phase 3 replaces this with real
  summarization + classification. Input sanitization (control chars,
  `<script>` tags, length limits) is already enforced via Pydantic validators.

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

## Next: Phase 5

Hub integration, rate limiting, audit logging, live operational statistics,
and the complete multi-agent dashboard remain for Phase 5.
