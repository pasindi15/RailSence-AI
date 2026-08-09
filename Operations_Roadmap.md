5-phase roadmap for your Operations & Delay-Prediction Agent, sequenced so each phase produces something demoable before you move to the next.

## Phase 1 — Service Scaffold + Dataset
**Goal:** Get `operations-agent/` running standalone with real (synthetic) data to build on.

- Scaffold FastAPI service: `main.py` with `POST /predict-delay`, `GET /route-status/{route_id}`, `POST /incident-report`, `GET /health`
- Build the synthetic historical dataset: route, station, scheduled time, actual time, weather, day-type, incident-type, delay-minutes (this single dataset feeds both your ML model and your IR corpus later)
- Set up Supabase (Postgres) connection for storing this data
- Stub out folder structure: `ml/`, `nlp/`, `rag/`, `hub_client.py`

**Deliverable:** Service boots, `/health` works, dataset exists and is queryable.

## Phase 2 — Delay Prediction Model (ML)
**Goal:** A working regressor plus an explainability story.

- Train a scikit-learn `RandomForestRegressor` or `GradientBoostingRegressor` on route/time/weather features
- Log feature importances (needed for both the LLM explanation and your evaluation writeup)
- Wire `predict.py` into `POST /predict-delay` — returns a numeric prediction
- Save/load model via `joblib`/pickle
- Record baseline metrics (MAE, RMSE, R²) on a held-out test split

**Deliverable:** Calling `/predict-delay` with route/time features returns a delay estimate with logged feature importances.

## Phase 3 — NLP: Incident Summarization + Classification
**Goal:** Turn messy staff free-text into structured, useful output.

- `summarize_incident.py` — LLM or HF pipeline condenses raw incident text into a 1–2 sentence operator brief
- `classify_incident.py` — classify incident type (signal fault / weather / mechanical / other)
- Wire both into `POST /incident-report`
- Sanitize incoming free text before it hits the LLM (Pydantic constraints + bleach, per the Section 2 security checklist)

**Deliverable:** Submitting a raw incident report returns a clean brief + a category label.

## Phase 4 — Retrieval (IR/RAG) + LLM Explanation Layer
**Goal:** Ground predictions in real precedent and produce plain-language output.

- Embed past incident descriptions (sentence-transformers `all-MiniLM-L6-v2`) into Supabase pgvector
- `incident_retriever.py` — given a new prediction, retrieve top 2–3 similar historical incidents
- LLM explanation layer: combine numeric prediction + top contributing features + retrieved incidents → plain-language explanation ("expect ~9 min delay — historically this route sees congestion at this hour and light rain is forecast")
- This becomes the full response body of `/predict-delay`

**Deliverable:** `/predict-delay` returns prediction + explanation + cited similar past incident — your strongest demo moment.

## Phase 5 — Hub Integration, Security, Dashboard, Evaluation ✅
**Goal:** Plug into the multi-agent system and make it presentable.

- `hub_client.py`: registers capabilities, sends MCP-style envelopes, and publishes `delay_alert` events to the Hub and Upstash Redis when the 5-minute threshold is crossed
- `/hub/message` accepts Passenger Agent `delay_check` envelopes and returns a grounded `delay_check_response`
- `/predict-delay` is protected by slowapi and every prediction/incident/hub action is written to `data/audit_log.jsonl`
- `/api/dashboard` provides live route heatmap data, hourly delay pressure, incident mix, feature importance, model/NLP metrics, alert events, and incident feed
- `ui/index.html` is a responsive operations control room with live polling, prediction drawer, incident triage, evaluation panels, and Hub status
- `/evaluation/ml/` and `/evaluation/nlp/` are read directly by the dashboard; displayed scores are the committed held-out evaluation artifacts

**Deliverable:** Full round trip — Passenger asks about a train → Hub → your agent responds with grounded explanation → `delay_alert` fires if threshold crossed → dashboard shows it live.

---
