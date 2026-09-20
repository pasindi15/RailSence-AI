# RailSense AI

RailSense AI is a multi-agent railway intelligence platform for passenger self-service, deterministic booking, delay prediction, railway operations, fraud detection, and rolling-stock maintenance.

This IT3041 Information Retrieval and Web Analytics project combines FastAPI services, machine-learning models, NLP, retrieval-augmented generation, Supabase PostgreSQL, and browser-based operations portals.

## Services and Portals

| Service | Port | Purpose | URL |
| --- | ---: | --- | --- |
| M1 Passenger Assistant | 8001 | Multilingual chat, NLU, FAQ RAG, and dispatch | `http://localhost:8001/docs` |
| M3 Communication Hub | 8002 | JWT verification, allowlisted routing, audit, rate limiting, circuit breakers | `http://localhost:8002/docs` |
| M3 Booking Agent | 8003 | Schedules, seat holds, fares, bookings, cancellations, waiting lists | `http://localhost:8003/docs` |
| Security and Fraud Agent | 8004 | IsolationForest risk scoring and review workflow | `http://localhost:8004/docs` |
| M2 Operations Agent | 8005 | Delay prediction, incident NLP/RAG, Control Room, Admin Console | `http://localhost:8005/` |
| M4 Maintenance Agent | 8006 | Asset health, reports, manual RAG, maintenance flags | `http://localhost:8006/` |
| Unified Web Gateway | 3000 | Passenger and staff portals | `http://localhost:3000/` |
| M1 React application | 5173 | Optional Vite passenger chat UI | `http://localhost:5173/` |

### Main URLs

- Passenger portal: `http://localhost:3000/user`
- Passenger chat: `http://localhost:3000/user/chat`
- Booking desk: `http://localhost:3000/user/booking`
- Ticket confirmation and QR verification: `http://localhost:3000/user/confirmation`
- Unified admin portal: `http://localhost:3000/admin`
- M2 Operations Control Room: `http://localhost:8005/`
- M2 Admin Operations Console: `http://localhost:8005/admin`
- M4 Asset Dashboard: `http://localhost:8006/`
- M4 Engineer Chat: `http://localhost:8006/chat-ui`

## Architecture

All internal agent traffic is hub-mediated. A sender creates a signed `AgentMessage`; the Communication Hub validates its Pydantic schema and JWT sender/audience, checks the interaction allowlist, records the event, and forwards it to the receiver's `/internal/messages` endpoint.

```mermaid
flowchart LR
    Browser[Passenger or Staff Browser] --> Gateway[Unified Gateway :3000]
    React[M1 React UI :5173] --> M1[M1 Passenger :8001]
    Gateway --> Hub[M3 Communication Hub :8002]
    M1 --> Hub
    Hub --> M2[M2 Operations :8005]
    Hub --> Booking[M3 Booking :8003]
    Hub --> Security[Security :8004]
    Hub --> Maintenance[M4 Maintenance :8006]
    M1 --> Chroma[(ChromaDB FAQ)]
    M2 --> Supabase[(Supabase PostgreSQL + pgvector)]
    Booking --> Supabase
    Maintenance --> Supabase
    Hub --> Audit[(Audit logs)]
```

The Supabase `trains` table is the canonical train registry. M4 can mark a train `OUT_OF_SERVICE`; M3 rejects new bookings with `TRAIN_UNDER_MAINTENANCE` until the flag is cleared. Seat availability and fares are deterministic booking-service decisions, and cancellation approval remains human-reviewed.

## Module Capabilities

### M1 Passenger Assistant

- English, Sinhala, and Tamil script detection and responses.
- Intent classification for schedules, fares, delays, bookings, complaints, and general questions.
- Station, train, date, time, class, and passenger-count extraction.
- ChromaDB FAQ retrieval with citations.
- Hub dispatch for delay, booking, cancellation, complaint, and maintenance queries.

### M2 Operations and Delay Prediction

- `GradientBoostingRegressor` delay prediction with exact historical lookup first.
- Sanitized incident classification and concise operator summaries.
- Supabase `pgvector` incident retrieval with local TF-IDF fallback.
- Grounded explanations containing prediction evidence, model version, retrieval method, and similar incidents.
- Control Room dashboard with network KPIs, route heatmaps, hourly delay pressure, incident mix, model metrics, and source indicators.

### M2 Admin Console

The M2 Admin Console uses bcrypt password hashes, signed expiring officer JWTs, and role-based permissions.

- Officer login, logout, profile, permissions, provisioning, role changes, password resets, activation, and audit history.
- Roles for administrators, operations engineers, managers, dispatchers, analysts, and viewers.
- Last-active-administrator lockout protection.
- Incident create/read/update/delete workflows.
- Delay-model retraining against Supabase or the CSV fallback.
- Timestamped model archives, metrics sidecars, feature-importance refresh, and rollback without restart.
- Read-only inter-agent audit search, filters, pagination, and Supabase-to-JSONL fallback.
- Explicit online/offline data-source indicators.

### M3 Communication Hub and Booking

The Hub provides schema validation, JWT authentication, interaction authorization, registry lookup, deduplication, rate limiting, circuit breakers, and SQLAlchemy audit persistence. The Booking Agent provides schedule lookup, first/second-class availability, deterministic fares, seat holds, idempotent booking mutations, ticket tokens, cancellations, waiting lists, and fraud-review states.

### Security and Fraud

Behavioral features cover booking velocity, cancellation ratios, duplicate seat attempts, route switching, and timing anomalies. The IsolationForest model returns `LOW`, `MEDIUM`, or `HIGH` risk with `ALLOW`, `REVIEW`, or `REJECT` decisions. Human reviewers can label confirmed fraud and false positives.

### M4 Maintenance

M4 scores asset health from service age, fault history, and sensor telemetry; extracts technician notes; searches equipment manuals; provides an engineer chatbot; persists maintenance flags; and reconciles flags with Supabase after restart.

### Unified Gateway

`frontend/serve.py` owns browser-facing orchestration. It serves the passenger and admin portals, extracts passenger intent, proxies schedule and availability requests, signs trusted Hub messages server-side, and never exposes database credentials or the inter-agent JWT secret to browsers.

## Evaluation Summary

| Component | Current benchmark summary |
| --- | --- |
| M2 delay model | 3,000 records; MAE 2.239 min, RMSE 2.876 min, R2 0.8716 |
| M2 incident NLP | 400 records; 100% classification accuracy |
| M2 incident retrieval | P@1 1.000, P@3 1.000, P@5 0.9987 |
| Security model | 600 records; 99.17% accuracy, 100% recall, 3.86 ms average latency |
| M4 health model | 600 records; MAE 3.757 points, RMSE 5.305 points, R2 0.8814 |
| M4 note NLP | 118 records; 89.83% accuracy |
| M4 manual retrieval | P@1, P@3, and P@5 all 1.000 |

The committed JSON artifacts under the relevant `evaluation/` directories are the source of truth for exact runs. Retraining can change the displayed metrics.

## Installation

Prerequisites: Python 3.11+, Node.js 18+ and npm, Git, and a Supabase project with PostgreSQL and `pgvector` for the full online deployment.

From the repository root:

```powershell
python -m pip install -r M2-operations-agent/requirements.txt
python -m pip install -r "M3-Comunication-Hub&Booking-Agent/agent-hub/requirements.txt"
python -m pip install -r "M3-Comunication-Hub&Booking-Agent/booking-agent/requirements.txt"
python -m pip install -r M4-maintenance-agent/requirements.txt
python -m pip install -r M2-admin-dashboard/requirements-admin.txt
python -m pip install psutil
```

M1 uses a dedicated environment:

```powershell
cd M1-passenger_assistant/backend
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm
cd ../..
```

Install the optional React app:

```powershell
cd M1-passenger_assistant/frontend
npm install
cd ../..
```

## Configuration

Create `.env` in the repository root and never commit real credentials:

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your-publishable-key
SUPABASE_SECRET_KEY=your-server-side-key
DATABASE_URL=postgresql://user:password@host:5432/postgres
JWT_SECRET_KEY=replace-with-a-long-random-secret
JWT_ALGORITHM=HS256
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-key
UPSTASH_REDIS_URL=https://your-instance.upstash.io
UPSTASH_REDIS_TOKEN=your-upstash-token
```

M1 also checks `M1-passenger_assistant/backend/.env`:

```powershell
Copy-Item .env M1-passenger_assistant\backend\.env
```

The Hub requires `DATABASE_URL` for normal runtime. Automated tests use SQLite unless `USE_LIVE_DB=1`. M2 and M4 use local CSV/JSONL/model fallbacks where supported when Supabase is unavailable.

## Running the Platform

### Windows complete startup

```powershell
.\start_all.ps1
```

This launches M1, M2, the Hub, Booking, Security, M4, the unified gateway, and the React UI in separate windows. The batch equivalent is:

```cmd
start_all.bat
```

Managed launchers are also available:

```powershell
python run_backend.py
python run_frontend.py
```

### Manual service commands

Run each command from its service directory:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload  # M1
python -m uvicorn main:app --host 127.0.0.1 --port 8002 --reload  # Hub
python -m uvicorn main:app --host 127.0.0.1 --port 8003 --reload  # Booking
python -m uvicorn main:app --host 127.0.0.1 --port 8004 --reload  # Security
python -m uvicorn main:app --host 127.0.0.1 --port 8005 --reload  # M2
python -m uvicorn main:app --host 127.0.0.1 --port 8006 --reload  # M4
python serve.py                                                        # Gateway, from frontend/
npm run dev                                                            # React, from M1-passenger_assistant/frontend/
```

### Unix alternate-port launcher

`start_all.sh` is a conflict-avoidance launcher for macOS/Linux. It uses M1, Hub, Booking, Security, and M2 ports `9001`-`9005`, gateway port `4000`, React port `5280`, and M4 login port `3002`:

```bash
chmod +x start_all.sh
./start_all.sh
```

## API and Health Checks

Every backend exposes `/health`. Important routes include:

| Service | Routes |
| --- | --- |
| M1 | `POST /chat`, `GET /health` |
| Hub | `POST /messages`, `/health`, `/ready`, `/api/hub/dashboard`, `/api/hub/timeline` |
| Booking | `/internal/messages`, booking, cancellation, hold, waiting-list, and schedule routes |
| Security | `POST /internal/fraud-score`, fraud-review routes, `/health` |
| M2 | `POST /predict-delay`, `POST /incident-report`, `GET/PATCH/DELETE /incidents`, `/api/dashboard`, `/health` |
| M2 admin | `POST /admin/api/login`, `/admin/api/me`, officer, model, audit, and health routes |
| M4 | `POST /asset-health`, `POST /maintenance-report`, `POST /chat`, `GET /manual-search`, train-flag routes |
| Gateway | `POST /api/chat`, `/api/booking-options`, booking/cancellation routes, `/api/admin/system-health` |

Open `/docs` on a FastAPI service for its generated Swagger contract.

## Testing

Run checks from the repository root:

```powershell
python test_portals.py
python test_full_system_integration.py
python test_integration.py
python scripts/test_m1_m2_integration.py
python scripts/test_m3_booking_integration.py
python scripts/test_m4_cross_agent_integration.py
python scripts/test_maintenance_delay_integration.py
python -m pytest test_m2_rbac.py -q
python test_startup_commands.py
```

The portal shortcut is `npm run test:portals`.

Model and retrieval evaluation commands:

```powershell
python security-agent/evaluate_model.py
python M2-operations-agent/ml/train_delay_model.py
python M2-operations-agent/nlp/evaluate_nlp.py
python M2-operations-agent/evaluation/rag/evaluate_retrieval.py
python M4-maintenance-agent/ml/train_health_model.py
python M4-maintenance-agent/nlp/evaluate_nlp.py
python M4-maintenance-agent/evaluation/rag/evaluate_retrieval.py
```

## Database Setup

Apply the SQL files for the services being deployed:

- `supabase_shared_trains.sql` for the canonical train registry.
- `M1-passenger_assistant/backend/supabase_schema.sql` for M1.
- `M3-Comunication-Hub&Booking-Agent/supabase_schema.sql` for Hub and Booking.
- `M4-maintenance-agent/supabase_schema.sql` and `supabase_setup_all.sql` for M4.
- `M2-operations-agent/supabase_phase5_schema.sql` and `admin/admin_schema.sql` for M2 operations, embeddings, audit, incident, model-run, and RBAC tables.

Use `scripts/seed_shared_trains.py` and `scripts/validate_shared_train_links.py` to seed and verify canonical train links.

## Repository Layout

```text
RailSence-AI/
├── frontend/                         Unified gateway and passenger/admin portals
├── M1-passenger_assistant/           Passenger backend and React frontend
├── M2-operations-agent/              Delay, incident, RAG, Control Room, and RBAC admin
├── M2-admin-dashboard/               Admin package and schema assets
├── M3-Comunication-Hub&Booking-Agent/ Central Hub, Booking, schemas, and SQL
├── M4-maintenance-agent/             Asset intelligence, manuals, flags, and engineer UI
├── security-agent/                   Fraud scoring service
├── shared/                           Cross-agent train helpers
├── scripts/                          Cross-agent and validation scripts
├── run_backend.py / run_frontend.py  Managed launchers
├── start_all.ps1 / .bat / .sh        Platform launchers
└── test_*.py                         Startup, portal, RBAC, and integration tests
```

## Security

Keep `.env`, Supabase server-side keys, JWT secrets, and local model/data state out of version control. Browser clients never receive database credentials or the inter-agent signing secret. The Hub rejects invalid or expired messages, free-text reports are sanitized, admin passwords are bcrypt-hashed, and the M2 audit explorer is read-only.

## Project Information

- Course: IT3041 - Information Retrieval and Web Analytics
- Institution: Sri Lanka Institute of Information Technology (SLIIT)
- Project: RailSense AI
- Package license metadata: MIT (see `package.json`)
