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

## Phase 5 — Hub Integration, Security, Dashboard, Evaluation
**Goal:** Plug into the multi-agent system and make it presentable.

- `hub_client.py`: respond to `delay_check` requests from the Passenger Agent via the Hub; publish `delay_alert` events (Redis/Upstash pub-sub) when predicted delay exceeds threshold
- Rate-limit `/predict-delay` (slowapi), log every prediction request for audit
- Build the Ops dashboard per the Section 2 design system: route heatmap, delay stats, model confidence, auto-summarized incident feed
- Populate `/evaluation/ml/` and `/evaluation/nlp/` with real MAE/RMSE and classification metrics — no invented numbers

**Deliverable:** Full round trip — Passenger asks about a train → Hub → your agent responds with grounded explanation → `delay_alert` fires if threshold crossed → dashboard shows it live.

---
