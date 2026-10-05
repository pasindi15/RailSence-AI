# RailSense AI

<p align="center"><img src="M1-passenger_assistant/frontend/public/logo.png" alt="RailSense AI logo" width="260"></p>

**Four AI agents. One seamless railway experience. Built for the future of Sri Lankan railways.**

RailSense AI is a multi-agent railway intelligence platform for Sri Lanka Railways. Four specialised
agents — a passenger assistant, an operations and delay-prediction agent, a communication hub with a
booking and fraud-security agent, and a maintenance agent — work together through one secure hub
and one shared train registry. It covers passenger self-service in English, Sinhala (including
romanized "Singlish") and Tamil, live train positions and delay prediction, deterministic booking with
QR tickets, fraud screening, incident management, and rolling-stock maintenance.

Built for **IT3041 – Information Retrieval and Web Analytics** (SLIIT) with FastAPI services, machine
learning, NLP, information retrieval and RAG, LLMs, Supabase PostgreSQL + pgvector, and browser portals.

---

## Contents

1. [Team](#team)
2. [How the assignment requirements are met](#how-the-assignment-requirements-are-met)
3. [Portals and ports](#portals-and-ports)
4. [Architecture](#architecture)
5. [Modules](#modules)
6. [Quick start](#quick-start)
7. [Installation and configuration](#installation-and-configuration)
8. [Running the platform](#running-the-platform)
9. [APIs and health checks](#apis-and-health-checks)
10. [Evaluation](#evaluation)
11. [Independent security and retrieval audit](#independent-security-and-retrieval-audit)
12. [Testing](#testing)
13. [Database setup](#database-setup)
14. [Security, ethics and responsible AI](#security-ethics-and-responsible-ai)
15. [Commercialisation plan](#commercialisation-plan)
16. [Repository layout](#repository-layout)
17. [Known limitations](#known-limitations)
18. [Troubleshooting](#troubleshooting)
19. [Project information](#project-information)

---

## Team

| Module | Responsibility | Member |
| --- | --- | --- |
| **M1** | Passenger Assistant — multilingual chat (incl. romanized Sinhala), NLU, FAQ RAG, passenger accounts, Choo widget | **Thisarani Kawya** |
| **M2** | Operations & Delay Prediction — ML, incident NLP/RAG, live journeys, Control Room, RBAC admin, Operations Assistant | **Pasindi Alawatta** (team leader) |
| **M3** | Communication Hub, Booking & Security — signed routing, audit, deterministic booking, fraud model | **Navoda Dasun** |
| **M4** | Maintenance & Asset Intelligence — asset-health ML, maintenance flags, manual RAG, engineer assistant, field observation log | **Primesh Marasingha** |

---

## How the assignment requirements are met

| Requirement | Where it is implemented |
| --- | --- |
| **One or more LLMs** | M1 passenger replies via **Gemini** or **OpenRouter** (chosen by `LLM_PROVIDER`, each with a fallback chain of models); M2 Operations Assistant with **Gemini function calling** over fixed data tools; M4 engineer assistant via **Groq** (Qwen). Every LLM answer is grounded: M2 and M4 reject any number or ID the LLM writes that is not in the retrieved evidence. |
| **NLP techniques** | Language detection (Unicode script → romanized-Sinhala lexicon → `langdetect`), intent classification (M1, M2 keyword rules + TF-IDF fallback, M4), **named-entity recognition** of stations, trains, dates, times, classes, passenger counts and IDs (M1 incl. romanized station aliases, M2 passenger query, M4 train/asset NER with typo tolerance), multi-turn context carry-over for follow-ups (M1), incident **classification and extractive summarisation** (M2), technician-note extraction (M4), NIC normalisation (M3), template NLG. |
| **Information retrieval** | Supabase **pgvector** + local **TF-IDF** incident retrieval (M2), manual retrieval with re-ranking (M4), ChromaDB FAQ retrieval (M1), IR over live records (flags, inspections, timetables). |
| **RAG** | M2 explains predictions with retrieved past incidents and sizes live map alerts by retrieving similar incidents; M4 answers from retrieved manual sections plus live flags/inspections; M1 answers FAQs with citations. |
| **Security features** | JWT-signed inter-agent messages verified by the Hub, allowlisted interactions, bcrypt officer **and passenger** passwords, signed expiring tokens, **chat ownership** (a passenger's ID comes only from a verified token), **role-based access control**, input sanitisation (bleach, schema validation, HTML rejection), rate limiting, circuit breakers, HMAC-hashed NIC numbers, append-only audit logs, admin-only incident approval. |
| **Agent communication protocols** | HTTP/JSON with an MCP-style `AgentMessage` envelope through the M3 Hub (`/messages`), agent start-up handshake (`POST /register`), gateway pass-through (`/svc/<agent>`), Upstash Redis pub/sub for delay and maintenance alerts. |
| **Fairness, explainability, transparency, data protection** | Model explanations and feature importance, confidence labels, "estimate, not a live signal" wording, cited sources on every answer, technique badges (LLM / NLP / IR / RAG) in the Operations Assistant, human-in-the-loop fraud and cancellation review, public map shows only admin-verified incidents with an allowlist of fields, masked NICs, secrets only server-side, romanized-Sinhala support for passengers without a Sinhala keyboard, a published independent audit (see below). |

---

## Portals and ports

Browsers use **two ports only** — one for passengers, one for officers. Every agent runs on an
internal port that `start.py` chooses on each laptop (defaults in `railsense_ports.json`). Pages reach
agents through the gateway (`/svc/m1`, `/svc/m2`, `/svc/m4`), so no page hard-codes a port.

| Side | Default port | What's there |
| --- | ---: | --- |
| **User side** | **3000** | Passenger portal and live train board, booking desk, confirmation / QR verification, M1 chat app (passenger sign-in), M2 delay popup, Choo assistant, verified-incident map |
| **Admin side** | **3001** | Officer login, command deck, M2 Control Room + Admin Console, M3 fraud and cancellation queues, Hub monitor, Security page, M4 maintenance, **Commercialisation plan** |

| Internal agent | Default port | Purpose |
| --- | ---: | --- |
| M1 Passenger Assistant | 8001 | Multilingual chat, NLU, FAQ RAG, passenger auth, chat sessions, dispatch |
| M3 Communication Hub | 8002 | JWT verification, allowlisted routing, audit, rate limiting, circuit breakers |
| M3 Booking Agent | 8003 | Schedules, seat holds, fares, bookings, cancellations, waiting lists |
| Security & Fraud Agent | 8004 | IsolationForest risk scoring and review workflow |
| M2 Operations Agent | 8005 | Delay prediction, live journeys, incident NLP/RAG, verified map, passenger answers, Operations Assistant, Control Room, Admin Console |
| M4 Maintenance Agent | 8006 | Asset health, maintenance flags, reports, field observation log, manual RAG, engineer assistant |

If a default port is busy, `start.py` stops it when an earlier RailSense run left it behind, or moves
to the next free port when another program owns it — and tells every agent and page.

Main URLs:

- Passenger portal: `http://localhost:3000/user` (chat `…/user/chat`, booking `…/user/booking`, tickets `…/user/confirmation`)
- Officer portal: `http://localhost:3001/admin` (login `http://localhost:3001/login`)
- Admin sections: `/admin/operations` (+ `/control-room`, `/prediction`, `/admin`, `/admin/officers`),
  `/admin/bookings`, `/admin/maintenance`, `/admin/security`, `/admin/hub`, `/admin/commercial`
- Opening an admin page on 3000 (or a passenger page on 3001) forwards you to the right side.

---

## Architecture

```mermaid
flowchart LR
    Browser[Passenger / officer browser] --> Gateway["Unified gateway<br/>user :3000 · admin :3001"]
    Gateway -- "/svc/m1" --> M1[M1 Passenger :8001]
    Gateway -- "/svc/m2" --> M2[M2 Operations :8005]
    Gateway -- "/svc/m4" --> M4[M4 Maintenance :8006]
    Gateway -- signed messages --> Hub[M3 Communication Hub :8002]
    M1 --> Hub
    M1 -- operations questions --> M2
    Hub --> M2
    Hub --> Booking[M3 Booking :8003]
    Hub --> Security[Security :8004]
    Hub --> M4
    M1 --> Chroma[(ChromaDB FAQ)]
    M1 --> Supabase
    M2 --> Supabase[(Supabase PostgreSQL + pgvector)]
    Booking --> Supabase
    Hub --> Audit[(Audit logs)]
    M2 -. delay alerts .-> Upstash[(Upstash Redis)]
    M4 -. maintenance alerts .-> Upstash
```

- **Hub-mediated agent traffic.** A sender creates an `AgentMessage` envelope signed with a JWT; the
  Hub validates the schema, sender and audience, checks the interaction allowlist, audits the event and
  forwards it to the receiver. Agents announce themselves at start-up (`POST /register`, read-only).
- **One train registry.** The Supabase `trains` table is canonical. M4 can mark a train
  `OUT_OF_SERVICE`; M3 then rejects new bookings with `TRAIN_UNDER_MAINTENANCE` until the flag clears.
- **Deterministic money and seats.** Availability and fares are computed by the booking service,
  never by an LLM; cancellations and flagged bookings are reviewed by humans.
- **Owned conversations.** Signed-in passengers see only their own chat sessions; anonymous callers
  (homepage, Choo, M2 hand-off) are stored with no owner and never appear in anyone's sidebar.
- **One clock.** Every "today", live position and map cut-off uses Asia/Colombo time.

---

## Modules

### M1 · Passenger Assistant — Thisarani Kawya

Full documentation: [`M1-passenger_assistant/README.md`](M1-passenger_assistant/README.md).

- **Languages:** Sinhala / Tamil / English script detection and replies in the passenger's language.
  **Romanized Sinhala ("Singlish")** such as *"mata colomba idala badullata ticket ekak ganna oni"* is
  detected through a lexicon (`backend/nlu/romanized.py`), mapped to intents and station aliases, and
  answered in Sinhala script.
- **Conversation memory:** the language chosen in a session is kept for that session, and follow-ups
  carry the earlier context forward (a bare *"3"* after *"how many passengers?"* is read as the
  passenger count).
- **NLU:** intent classification (schedules, fares, delays, train status, bookings, cancellations,
  policies, complaints) and entity extraction (stations, train, date, time, class, passenger count).
- **RAG:** ChromaDB FAQ retrieval with citations. The LLM is **Gemini** when `LLM_PROVIDER` names a
  Gemini model (with a lighter → fuller model fallback), otherwise **OpenRouter** (tries several free
  models in turn); with no key, the raw FAQ text is returned.
- **Passenger accounts and chat ownership (`backend/auth.py`):** bcrypt passwords, 12-hour JWTs signed
  with `JWT_SECRET_KEY`, and a passenger ID taken only from a verified token — never from the request.
  Signed-in passengers can list, rename, pin and delete their own sessions. Demo accounts (Kavya,
  Dilshan, Nimal, Guest) are seeded by `backend/supabase_schema.sql`. `M1_REQUIRE_AUTH=false` is a
  kill switch that restores open access for a demo.
- **Hand-off:** train operations questions ("any train to Polonnaruwa after 19:15?", "where is the
  Night Mail now?", "when will DM-8055 reach Kurunegala?") are answered by M2 from the live timetable
  (`/passenger/query`); fares, policies and bookings stay with M1.
- **Frontend:** React chat app served at `/user/chat` with an animated rail-scene sign-in page and the
  shared RailSense logo, plus the **Choo** floating assistant on the passenger portal.
- Runs on its **own venv** (`backend/venv`, pinned `chromadb` that matches the stored index); reads
  `backend/.env` first, then the root `.env`.

### M2 · Operations & Delay Prediction — Pasindi Alawatta

Full documentation: [`M2-operations-agent/README.md`](M2-operations-agent/README.md).

- **Delay model:** `GradientBoostingRegressor` with exact historical lookup first; retrained on the
  refreshed corpus (3,900 records, 2026-03-01 → 2026-09-27): **MAE 2.25 min, R² 0.894**.
- **Live journeys (`live_tracker.py`):** station-by-station timetable (intermediate times by track
  distance), live position on the Asia/Colombo clock, correct overnight handling (a 19:15 → 04:30 train
  is "not yet departed" at 18:52), and **verified map incidents on a train's path delay every later
  stop**, each sized by retrieving similar past incidents (IR).
- **Passenger popup (`/passenger/ask`)** and **free-text passenger queries (`/passenger/query`)**:
  intent rules + TF-IDF fallback for typos, station/train/time NER, journey search ("trains to X after
  19:15"), station ETAs, incident and network overviews.
- **Incident pipeline:** sanitised reports → classification + summarisation → `pending` → admin
  Approve/Reject → verified map on all three portals within 5 s, current day only.
- **Operations Assistant:** Gemini function calling over seven role-filtered data tools, number guard,
  fixed refusal messages, per-user history, and **technique badges** (LLM · NLP · IR · RAG · ML ·
  Explainable AI · Security · Protocol · Responsible AI) computed from what actually ran.
- **Control Room and Admin Console:** 3D banners, KPIs, heatmaps, model metrics, incident management,
  officer RBAC (bcrypt, signed tokens, last-admin lock-out), retraining with archived versions and
  rollback, audit explorer, live health (Supabase, Hub, Upstash).
- **Corpus refresh:** `data/refresh_corpus.py` keeps every record, moves dates up to yesterday, adds
  recent records, upserts Supabase and indexes new notes in pgvector (re-runnable).

### M3 · Communication Hub, Booking & Security — Navoda Dasun

- **Hub:** schema validation, JWT authentication, interaction authorisation, registry lookup,
  deduplication, rate limiting, circuit breakers, SQLAlchemy audit, live monitor
  (`/api/hub/dashboard`, `/api/hub/timeline`), start-up handshake `POST /register`.
- **Booking:** schedules, first/second-class availability, deterministic fares, seat holds, idempotent
  bookings, QR e-tickets and verification, cancellations with NLP-explained human review, waiting lists,
  maintenance-aware booking blocks, admin booking copilot (Bookings & Revenue workspace only).
- **Security & Fraud agent:** behavioural features (booking velocity, cancellation ratio, duplicate
  seats, route switching, timing) → IsolationForest → `LOW/MEDIUM/HIGH` with `ALLOW/REVIEW/REJECT`;
  reviewers label outcomes in the fraud queue.

### M4 · Maintenance & Asset Intelligence — Primesh Marasingha

- Asset-health scoring from service age, fault history and telemetry (per-type gradient boosting),
  technician-note extraction, maintenance reports, manual search, maintenance flags that sync to the
  train registry.
- **Field Observation Log:** technician and passenger reports shown as cards (same style as the
  passenger report UI) with search and filter controls.
- **Engineer assistant (`/chat`, `rag/ops_status.py`)** answers operational questions with
  **NLP → IR → RAG → LLM**: intent + train NER (name, typo, M4 id `T-00x`, service number, shared id,
  loco or asset id) → live flags, latest inspections and open reports → manual sections retrieved for the
  specific fault or the fitness-to-run limits (re-ranked) → Groq LLM answer that is rejected if it
  contains any number or ID not in the evidence (template fallback). Examples: "What trains are
  unavailable today due to maintenance issues?", "Is the Yal Devi running today? I have a booking on
  it." Technical questions ("how do I diagnose an oil leak?") use the manual RAG as before.
- Maintenance alerts published to Upstash Redis (`maintenance_alert`); LLM via Groq. Keys live in
  `M4-maintenance-agent/.env` (git-ignored).

### Unified gateway (`frontend/serve.py`)

Serves both public sides, forwards pages to the correct side, publishes `/railsense-config.js` (the
ports in effect), serves the built M1 chat app at `/user/chat`, passes browser calls through to agents
(`/svc/m1|m2|m4`), signs trusted Hub messages server-side, proxies booking and admin APIs, and never
exposes database credentials or the inter-agent secret to browsers. One RailSense logo is used in every
header (M1–M4, user and admin). The admin side (`frontend/admin.html`) also hosts the
**Commercialisation** page at `/admin/commercial` (see [Commercialisation plan](#commercialisation-plan)).

---

## Quick start

```bash
git clone <repo> && cd RailSence-AI
cp .env.example .env            # fill in the team's shared values (ask the team leader privately)
python check_setup.py           # shows exactly what this laptop is missing
python start.py                 # starts everything and prints the two URLs
```

Open `http://localhost:3000/user` (passengers) and `http://localhost:3001/admin` (officers).

---

## Installation and configuration

Prerequisites: **Python 3.10+**, **Node.js 18+** (npm), Git. Everyone uses the same Supabase project.

Agents M2, M3, Security and M4 run on **one shared Python** (per-module venvs differ between laptops,
and Windows Smart App Control can block packages inside a venv). From the repository root:

```bash
python -m pip install -r M2-operations-agent/requirements.txt
python -m pip install -r "M3-Comunication-Hub&Booking-Agent/agent-hub/requirements.txt"
python -m pip install -r "M3-Comunication-Hub&Booking-Agent/booking-agent/requirements.txt"
python -m pip install -r M4-maintenance-agent/requirements.txt
python -m pip install psutil
```

**M1 is the exception:** its ChromaDB index must be read by the exact `chromadb` version that built it,
so M1 uses its own venv. `start.py` runs any agent that has a `venv/` folder with that venv's Python.

```bash
cd M1-passenger_assistant/backend
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt     # macOS/Linux: venv/bin/python
```

If a pinned package has no build for your Python (for example old `pandas` on Python 3.13), install only
the missing packages at current versions instead of downgrading working ones — `check_setup.py` lists
them per agent.

**`.env`** (git-ignored; template in `.env.example`, which explains every key):

| Key | Needed for |
| --- | --- |
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `DATABASE_URL` | Shared database (required) |
| `JWT_SECRET_KEY` | Gateway ↔ Hub signed messages and M1 passenger tokens (required, identical on every laptop) |
| `NIC_HMAC_SECRET` | NIC hashing for bookings (required, **identical on every laptop** or duplicate/fraud checks disagree) |
| `ADMIN_INITIAL_PASSWORD` | First M2 admin password (set it — otherwise a documented default is used; see the audit) |
| `GEMINI_API_KEY` | M2 Operations Assistant LLM, and M1 when `LLM_PROVIDER` is a Gemini model (optional — rule-based fallback) |
| `LLM_PROVIDER` | M1 provider: a Gemini model id (e.g. `gemini-3.5-flash-lite`) selects Gemini; empty uses OpenRouter |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | M1 LLM replies via OpenRouter (optional, needs the `openai` package; model list is comma-separated) |
| `M1_REQUIRE_AUTH` | `false` re-opens M1 chat history without sign-in (demo kill switch; default on) |
| `UPSTASH_REDIS_URL`, `UPSTASH_REDIS_TOKEN` | M2 delay-alert pub/sub (optional) |

`M4-maintenance-agent/.env` holds M4's own `UPSTASH_REDIS_URL/TOKEN` and `GROQ_API_KEY`. Don't put
ports or agent URLs in `.env` — the launcher sets them.

---

## Running the platform

```bash
python start.py
```

It checks the setup, chooses the ports, builds the M1 chat app when its sources are newer than the
build, starts all six agents and both portal sides in one terminal (logs prefixed by service, each
agent with its own venv when it has one), waits until each is healthy and prints the two URLs. If the
`all-MiniLM-L6-v2` embedding model is already cached, it sets `HF_HUB_OFFLINE=1` so a slow network
cannot stall M2/M4 start-up. `Ctrl+C` stops everything.

| Command | What it does |
| --- | --- |
| `python start.py --status` | Which ports are free / used by RailSense / used by other programs |
| `python start.py --stop` | Stop everything this repository started (never other programs) |
| `python start.py --no-build` / `--rebuild` | Skip / force the M1 chat build |
| `python start.py --no-reload` | Run agents without auto-reload (lighter on older laptops) |
| `python check_setup.py` | Packages per agent, `.env` keys (names only), Node.js, ports |

`start_all.bat`, `start_all.ps1`, `start_all.sh`, `backend.bat`, `frontend.bat` and `stop_all.ps1` are
one-line wrappers around `start.py`; `M1-passenger_assistant/backend/run.bat` / `run.ps1` start M1 alone
with its venv. `run_backend.py` / `run_frontend.py` (used by the startup tests) read the same
`railsense_ports.json`. To run one agent by hand, use its port from that file, e.g. from
`M2-operations-agent/`: `python -m uvicorn main:app --host 127.0.0.1 --port 8005 --reload`.

The M1 chat build (`M1-passenger_assistant/frontend/dist/`) is git-ignored; after pulling new M1
frontend changes, restart `start.py` or run `npm run build` in `M1-passenger_assistant/frontend`.

---

## APIs and health checks

Every backend exposes `/health`; open `/docs` on a service for its Swagger contract.

| Service | Key routes |
| --- | --- |
| Gateway | `/user…`, `/admin…` (incl. `/admin/commercial`), `/login`, `/railsense-config.js`, `/svc/{m1\|m2\|m4}/…`, `POST /api/chat`, `/api/train-board`, `/api/booking-options`, booking/cancellation routes, `/api/admin/*`, `/api/admin/system-health`, `/api/hub/*` |
| M1 | `POST /auth/login`, `GET /auth/me`, `POST /chat`, `POST /chat/quick`, `GET /chat` (own sessions), `GET /chat/{session}/history`, `PATCH /chat/{session}/title`, `PATCH /chat/{session}/pin`, `DELETE /chat/{session}`, `GET /trains/{id}/details`, `POST /feedback`, `/health` |
| Hub | `POST /messages`, `POST /register`, `/health`, `/ready`, `/api/hub/dashboard`, `/api/hub/timeline` |
| Booking | `/internal/messages`, booking, hold, cancellation, waiting-list, schedule, ticket-verification routes |
| Security | `POST /internal/fraud-score`, fraud-review routes, `/health` |
| M2 | `POST /predict-delay`, `POST /passenger/ask`, `POST /passenger/query`, `POST /incident-report`, `/incidents` (+ `approve` / `reject`), `/api/incidents/map-feed`, `/api/dashboard`, `/api/route-options`, `/api/trains`, `/api/stations`, `/api/ops-agent/ask`, `/history`, `/capabilities` |
| M2 admin | `POST /admin/api/login`, `/admin/api/me`, officer, model, audit and health routes |
| M4 | `POST /chat`, `POST /asset-health`, `POST /maintenance-report`, `GET /manual-search`, `POST/DELETE /api/flag-train`, `/api/train-status/{id}`, `/api/trains-under-maintenance`, `/api/dashboard`, `/hub/message` |

---

## Evaluation

Team evaluations (committed artifacts under each module's `evaluation/` directory are the source of
truth; retraining updates them):

| Component | Result |
| --- | --- |
| M1 romanized Sinhala NLU | 56 queries; language detection, intent, origin and destination all **100%** (`M1-passenger_assistant/evaluation/romanized_sinhala/`) |
| M1 prompt injection / jailbreak | 15 cases re-graded under a strict rubric: **12 PASS, 2 FAIL** (PI-10 cross-passenger request not explicitly refused; PI-13 Sinhala fare retrieval miss), 1 no-harm-observed (`M1-passenger_assistant/evaluation/prompt_injection/`) |
| M2 delay model | 3,900 records (3,120 train / 780 test); **MAE 2.254 min, RMSE 2.837 min, R² 0.894** |
| M2 incident NLP | 400 records; 100% classification accuracy |
| M2 incident retrieval | P@1 1.000, P@3 1.000, P@5 0.999 (corpus-derived queries) |
| Security model | 600 records; 99.17% accuracy, 100% recall, 3.86 ms average latency |
| M4 health model | 600 records; MAE 3.757, RMSE 5.305, R² 0.881 |
| M4 note NLP | 118 records; 89.83% accuracy |
| M4 manual retrieval | P@1, P@3 and P@5 all 1.000 (shipped evaluation set) |

Independent retrieval figures from the Student 4 audit (24 held-out queries per module, commit
`8b66312`) are lower and are published here alongside the team numbers:

| Retriever | Independent P@1 | Note |
| --- | --- | --- |
| M1 FAQ (ChromaDB, MiniLM) | 0.542 | English 1.000 · Sinhala 0.375 · Tamil 0.250 — English-only embeddings |
| M2 incidents | 0.875 | Team set uses queries derived from the corpus |
| M4 manuals (TF-IDF) | 0.792 | No relevance cut-off; off-topic false-positive rate 0.5 |

---

## Independent security and retrieval audit

`student4_audit/` holds an evidence-based audit of all four modules (16 tests across retrieval
accuracy and manipulation, hallucination, source reliability, authentication, authorisation, API
security and communication-protocol security; 4 tests per module) run against commit `8b66312`
(2026-09-28). Outcome: **6 PASS · 7 PARTIAL · 3 FAIL**. Start with `student4_audit/RESULTS.md`;
details in `findings.md`, `endpoint_inventory.md`, `audit_gaps.md` and `evidence/<TEST_ID>/`.
Test scripts are in `student4_audit/scripts/`.

| Severity | Findings |
| --- | --- |
| High | F-01 default M2 admin password still valid · F-02 hard-coded engineer credentials in M4 · F-03 admin, fraud, cancellation and Hub endpoints reachable without auth on the public port · F-16 cleartext NICs in fraud-case payloads |
| Medium | F-04 CORS reflects any origin with credentials · F-05 internal endpoints without independent auth (M4 skips JWT) · F-06 gateways bind `0.0.0.0` · F-07 retrieval below team claims and Sinhala/Tamil gap · F-12 one HS256 secret for agents and officers |
| Low / Info | F-08 pending incidents in Ops Assistant context · F-09 no security headers, `/docs` open · F-10 no rate limit on M1 `/chat` and M2 `/incident-report` · F-11 chat history readable by session ID · F-13 unsigned Upstash events · F-14 no request-body size cap · F-15 M4 assistant answers out-of-role |

**Since the audit:** F-11 is addressed — M1 history, listing, rename, pin and delete now require a
passenger token and check ownership (`backend/auth.py`, `tests/test_chat_ownership.py`). The other
findings are open; each has an immediate and a long-term mitigation in `findings.md`.

---

## Testing

```bash
python -m pytest M2-operations-agent/tests -q          # 57 tests incl. live tracker and passenger query NLP
python -m pytest "M3-Comunication-Hub&Booking-Agent/tests" -q
python -m pytest test_m2_rbac.py -q
python test_portals.py
python test_startup_commands.py
python test_full_system_integration.py
python test_integration.py
python scripts/test_m1_m2_integration.py
python scripts/test_m3_booking_integration.py
python scripts/test_m4_cross_agent_integration.py
```

M1 runs on its own venv (312 tests: chat flows, ownership, conversation context and language,
romanized Sinhala, RAG, routing, Hub client, session-schema resilience):

```bash
cd M1-passenger_assistant/backend
venv\Scripts\python.exe -m pytest tests -q                      # macOS/Linux: venv/bin/python
```

Model, retrieval and robustness evaluation:

```bash
python security-agent/evaluate_model.py
python M2-operations-agent/ml/train_delay_model.py
python M2-operations-agent/nlp/evaluate_nlp.py
python M2-operations-agent/evaluation/rag/evaluate_retrieval.py
python M4-maintenance-agent/ml/train_health_model.py
python M4-maintenance-agent/nlp/evaluate_nlp.py
python M4-maintenance-agent/evaluation/rag/evaluate_retrieval.py
python M1-passenger_assistant/evaluation/romanized_sinhala/run_eval.py      # offline, no server or LLM
python M1-passenger_assistant/evaluation/prompt_injection/run_pi_tests.py   # needs M1 running
```

The audit scripts (`student4_audit/scripts/test_*.py`) need the full platform running and write
evidence under `student4_audit/evidence/`. Some create test records (prefixed `S4TEST`) in agent data
files; remove them afterwards.

---

## Database setup

- `supabase_shared_trains.sql` — canonical train registry (`scripts/seed_shared_trains.py`,
  `scripts/validate_shared_train_links.py`).
- `M1-passenger_assistant/backend/supabase_schema.sql` — M1 chat sessions and messages, plus the
  passenger accounts table with the four demo accounts (bcrypt hashes) and session ownership.
- `M3-Comunication-Hub&Booking-Agent/supabase_schema.sql` — Hub and Booking.
- `M4-maintenance-agent/supabase_schema.sql`, `supabase_setup_all.sql` — M4.
- `M2-operations-agent/supabase_phase5_schema.sql`, `admin/admin_schema.sql`,
  `admin/incident_map_migration.sql`, `admin/ops_agent_migration.sql` (adds `answer_method`) — M2.
  M2 runs on local fallbacks until these are applied.

---

## Security, ethics and responsible AI

- **Secrets:** `.env` files, Supabase server keys, JWT and HMAC secrets stay out of git and out of the
  browser. Share team values privately; rotate any key that was pasted into a chat. Set
  `ADMIN_INITIAL_PASSWORD` so the documented default admin password is never live.
- **Authentication and access:** bcrypt officer and passenger passwords, signed expiring tokens,
  role-based tools and pages, last-admin lock-out, admin-only incident approval and model management,
  passenger chat ownership enforced on the server.
- **Input handling:** schema validation, bleach sanitisation, HTML rejection in incident text, rate
  limits on public endpoints, signed and deduplicated Hub messages.
- **Grounding and transparency:** answers cite their sources; LLM output with unsupported numbers or IDs
  is replaced by a grounded template; predictions carry confidence and "estimate" wording; technique
  badges show which AI techniques produced an answer; independent audit figures are published next to
  the team's own.
- **Prompt-injection resistance (M1):** system-prompt rules, deterministic pre-LLM gates, confirmation
  steps that cannot be skipped by instruction, and URL parameters built with `urlencode` — tested in
  `evaluation/prompt_injection/`.
- **Fairness:** replies in the passenger's language, including romanized Sinhala; the audit's
  Sinhala/Tamil retrieval gap (F-07) is tracked as a known limitation.
- **Human in the loop:** fraud reviews, cancellations and public incident alerts require a person.
- **Data protection:** NICs are HMAC-hashed and masked; the public map exposes only verified incidents
  and an allowlist of fields; audit logs are read-only in the UI.

---

## Commercialisation plan

RailSense AI is positioned as a **business-to-government (B2G) SaaS suite** for railway authorities,
replacing four disconnected tools with one connected system. The full plan — value proposition,
customer segments, tiers, cost drivers, deployment options, go-to-market and revenue model — is
presented to officers at **`/admin/commercial`** (admin side, drawer item *Commercialisation*), with a
pilot cost estimator.

| | Starter | Operations | Enterprise |
| --- | --- | --- | --- |
| Agents | M1 Passenger Assistant; basic M2 delay prediction and live train board | + M2 Control Room, Admin Console, incident pipeline, Operations Assistant; M4 Maintenance | All four agents: + M3 Booking with QR tickets, Security and Fraud screening, Hub integrations |
| Coverage | One route or region | One region, multiple routes | Network-wide |
| Officer seats | Up to 5 | Up to 25 | Unlimited, custom roles |
| Price (indicative) | LKR 40,000 / station / month (≈ USD 135) | LKR 85,000 / station / month (≈ USD 285) | Custom, from ≈ LKR 9,000,000 / year (≈ USD 30,000) |
| Onboarding | LKR 250,000 per region | LKR 250,000 per region | In the quote |

- **Segments:** primary — Sri Lanka Railways and its stations and control rooms; secondary — regional
  rail, metro and bus authorities; extension — private, tourist and freight operators.
- **Example:** a 10-station regional pilot on Operations costs LKR 850,000 / month (LKR 10.2 M / year)
  plus LKR 250,000 onboarding.
- **Go-to-market:** pilot one region → measure agreed indicators (questions answered without staff,
  incident-to-verified-alert time, prediction error, confirmed fraud reviews, maintenance events
  avoided) → expand tiers and regions.
- **Deployment:** cloud SaaS, single server / containers (`start.py`, `docker-compose.yml`), or
  on-premise — every LLM path has a deterministic fallback and retrieval can run on local TF-IDF.

Prices are planning figures (LKR 300 per USD), to be finalised with the customer after a pilot.

---

## Repository layout

```text
RailSence-AI/
├── start.py · check_setup.py · railsense_ports.json   one launcher, setup check, port registry
├── frontend/                          unified gateway (serve.py), passenger / admin portals, logo assets
├── M0-homepage/                       project landing page (Next.js)
├── M1-passenger_assistant/            passenger backend (FastAPI, own venv), React chat app, evaluation/
├── M2-operations-agent/               delay ML, live tracker, incident NLP/RAG, Control Room, RBAC admin, Operations Assistant
├── M3-Comunication-Hub&Booking-Agent/ central Hub, Booking agent, shared schemas and SQL
├── security-agent/                    fraud scoring service
├── M4-maintenance-agent/              asset intelligence, manuals, flags, field log, engineer assistant (rag/ops_status.py)
├── shared/                            train registry helpers, ports.py
├── scripts/                           seeding, validation and cross-agent tests
├── student4_audit/                    independent security and retrieval audit (results, findings, evidence, scripts)
├── prep.md                            final-report fact base (every claim linked to its source file)
├── start_all.* · backend.bat · frontend.bat · stop_all.ps1   wrappers around start.py
└── test_*.py                          startup, portal, RBAC and integration tests
```

---

## Known limitations

- **Open audit findings:** see [the audit section](#independent-security-and-retrieval-audit) — most
  urgently the default M2 admin password (F-01), M4 hard-coded engineer credentials (F-02) and admin /
  fraud / Hub endpoints reachable without auth on the public port (F-03, F-16).
- **Multilingual retrieval:** M1 FAQ retrieval uses English-only embeddings, so Sinhala and Tamil
  questions retrieve less accurately than English (P@1 0.375 / 0.250 vs 1.000), and no retriever has a
  relevance cut-off yet.
- **M1 prompt-injection gaps:** a request for another passenger's data is not refused explicitly
  (nothing leaks, but no refusal is shown — PI-10), and one Sinhala fare question misses retrieval
  (PI-13).
- **M4 is not connected to the shared database yet** (it reads only its own `.env`, which has no
  Supabase keys). It works on local data, so the "flag a train → Booking stops selling seats" link does
  not reach M3, and the invented-train-ID check is skipped. Loading the root `.env` in M4 is the fix
  (owner decision).
- **M4 uses its own train numbers** (e.g. Yal Devi #1001 / `T-003`) while the rest of RailSense uses
  service numbers such as 4085; the M4 assistant accepts both.
- **M1 routing:** "which trains are unavailable due to maintenance" and "is my booked train running"
  are not yet routed to M4 from the passenger chat.
- Intermediate station times are estimated from track distance between the published departure and
  arrival, not from an official per-stop timetable.
- Commercialisation prices are indicative planning figures, not a quote.
- `spacy` is listed in M1's requirements but not used by the code.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| A page works on one laptop but not another | `python check_setup.py`, then `python start.py` (never start agents with old per-port commands) |
| "Port in use" / services on odd ports | `python start.py --status`; RailSense leftovers are stopped automatically, other programs are skipped |
| `/user/chat` still shows the old login or UI | The M1 build is stale — restart `start.py` (rebuilds when sources are newer) or `npm run build` in `M1-passenger_assistant/frontend`, then hard-refresh (Ctrl+Shift+R) |
| M1 RAG fails with `KeyError: '_type'` | M1 ran on the wrong `chromadb` — create `M1-passenger_assistant/backend/venv` and install its requirements; `start.py` then uses it |
| M1 chat asks to sign in / history is empty | Sign in with a demo passenger account; chats made anonymously (homepage, Choo) are not linked to an account |
| Choo says "can't reach the assistant" | M1 is not running — check the `[M1 …]` lines in the `start.py` log |
| M1 replies are raw FAQ text | Set `GEMINI_API_KEY` + `LLM_PROVIDER`, or `OPENROUTER_API_KEY` (and `pip install openai` in M1's venv), then restart |
| M2/M4 start slowly or hang on a model download | Run once online to cache `all-MiniLM-L6-v2`; later starts use it offline |
| Officer pages ask to log in again | The admin side moved to port 3001 — log in once there |

---

## Project information

- **Course:** IT3041 – Information Retrieval and Web Analytics
- **Institution:** Sri Lanka Institute of Information Technology (SLIIT)
- **Project:** RailSense AI — Thisarani Kawya (M1), Pasindi Alawatta (M2, team leader), Navoda Dasun (M3), Primesh Marasingha (M4)
- **Licence metadata:** MIT (see `package.json`)
