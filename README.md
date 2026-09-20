# 🚆 RailSense AI — Autonomous Multi-Agent Railway Intelligence System

> **IT3041 – Information Retrieval & Web Analytics**  
> **Sri Lanka Institute of Information Technology (SLIIT)**  
> Comprehensive Multi-Agent Railway Intelligence System integrating Large Language Models (LLMs), Natural Language Processing (NLP), Information Retrieval (IR/RAG), Machine Learning, Anomaly Detection, and MCP-Style Agent Communication Protocols.

---

## 📌 Executive Summary

**RailSense AI** is an enterprise-grade agentic artificial intelligence platform designed to modernize railway network management, passenger self-service, predictive rolling-stock maintenance, deterministic ticketing, and real-time operational reliability.

The platform coordinates **six specialized backend microservices and agents** alongside **two rich frontend web applications** connected through a centralized, JWT-authenticated **Agent Communication Hub**:

1. 🧑‍💼 **Module 1 (M1) — Passenger Assistant Agent (Port 8001)**: Multilingual conversational AI (English, Sinhala, Tamil), script detection, spaCy entity extraction, ChromaDB FAQ RAG, delay dispatch, booking prefill, and complaint escalation.
2. 🚦 **Module 2 (M2) — Operations & Delay-Prediction Agent (Port 8005)**: Trained `GradientBoostingRegressor` ML delay predictor, train-specific historical observation retrieval, incident NLP triage and summarization, Supabase `pgvector` historical RAG, grounded plain-language explanations, and live Operations Control Room dashboard.
3. 🛡️ **Module 3 (M3) — Central Communication Hub (Port 8002)**: Asynchronous MCP-style JSON envelope router, strict JWT signature verification, agent service registry, circuit breakers, and privacy-preserving audit trail.
4. 🎟️ **Module 3 (M3) — Booking & Reservation Agent (Port 8003)**: Deterministic seat inventory and fare calculation engine against Supabase PostgreSQL, human-in-the-loop cancellation workflow with NLP policy recommendations.
5. 🔒 **Security & Fraud Detection Agent (Port 8004)**: Behavioral anomaly scoring using `IsolationForest` to detect seat-hoarding, botting, and suspicious transactions in under 5ms, with grounded policy explanations.
6. 🔧 **Module 4 (M4) — Maintenance & Asset Intelligence Agent (Port 8006)**: Telemetry-driven predictive asset health scoring, technician note NLP extraction, multi-document equipment manual RAG (`pgvector` + TF-IDF fallback), RED alert publishing, and Maintenance Engineer Chatbot.
7. 🌐 **Unified Web Gateway & Application (Port 3000)**: Complete station intelligence web portal featuring the **Passenger Portal** (`/user`), **Admin Control Center** (`/admin`), interactive train status board, QR ticket verification, and booking management.
8. ⚛️ **M1 React Passenger Application (Port 5173)**: High-performance Vite + React glassmorphism chat application with multi-script conversation streams and citation grounding.

---

## ✅ Completion Status & Empirical Evaluation Evidence

All modules are implemented, integrated via canonical Supabase tables and the Agent Hub, and rigorously verified.

| Module | Logical Service | Completion Evidence | Primary Data & Evaluation Metrics |
|---|---|---|---|
| **M1** | `passenger-agent` | Trilingual NLU, ChromaDB vector FAQ index, session memory, live Hub dispatch to M2/M3 | Schedules, fares, policies; ChromaDB vector collection; Gemini 1.5/2.5 Flash fallback |
| **M2** | `operations-agent` | GBR delay regressor, incident NLP classifier, Supabase pgvector RAG, grounded explanations, Control Room & Admin UI | 3,000 historical operations records.<br>• Delay MAE: **2.239 min**, RMSE: **2.876 min**, R²: **0.8716**<br>• Incident NLP Accuracy: **100%** (400 records)<br>• Incident RAG Precision: **P@1: 1.000**, **P@3: 1.000**, **P@5: 0.9987** |
| **M3** | `agent-hub` | Asynchronous router, PyJWT validation, Pydantic v2 schemas, audit trail, circuit breaker | Supabase PostgreSQL audit tables; 0% routing failure in end-to-end integration tests |
| **M3** | `booking-agent` | Deterministic seat inventory, fare rules, cancellation pipeline with NLP preview | Canonical `train_schedules` & `bookings` tables; zero hallucinated fares or overbooking |
| **Security** | `security-agent` | `IsolationForest` anomaly scoring, behavioral feature extractor, grounded policy summary | 600 behavioral telemetry records.<br>• Accuracy: **99.17%**<br>• Precision: **93.51%**, Recall: **100.00%**<br>• F1-Score: **0.9664**<br>• Average Latency: **3.86 ms** (< 5 ms SLA) |
| **M4** | `maintenance-agent` | Predictive health model, technician note NLP, technical manual RAG, Engineer Chatbot | 600 asset records; 5 technical manuals.<br>• Health MAE: **3.757 pts**, RMSE: **5.305 pts**, R²: **0.8814**<br>• Note NLP Accuracy: **89.83%** (118 records)<br>• Manual RAG: **P@1: 1.000**, **P@3: 1.000**, **P@5: 1.000** |
| **Gateway** | `unified-frontend` | Passenger booking, live chat, interactive train board, Admin control center, audit queues | Unified FastAPI server on Port 3000 hosting `/user` and `/admin` portals |

---

## 🏗️ System Architecture & Inter-Agent Communication

All inter-agent communication is **strictly hub-mediated** using standard MCP-style JSON envelopes (`AgentMessage`). Direct peer-to-peer invocation between internal agents is forbidden, ensuring centralized authentication, auditability, and circuit breaking.

```mermaid
flowchart TD
    subgraph Clients["Human & Web Clients"]
        UP["Passenger Portal & Chat<br/>http://localhost:3000/user"]
        AP["Admin Control Center<br/>http://localhost:3000/admin"]
        RC["M1 React Chat UI<br/>http://localhost:5173"]
    end

    subgraph Gateway["Web Gateway (Port 3000)"]
        GW["Unified Web Server<br/>(frontend/serve.py)"]
    end

    subgraph Hub["Central Security Gateway (Port 8002)"]
        M3H["M3 Agent Communication Hub<br/>JWT Auth • Async Router • Audit Trail"]
    end

    subgraph Agents["Autonomous AI Microservice Agents"]
        M1["M1 Passenger Assistant<br/>(Port 8001)<br/>• Trilingual NLU<br/>• ChromaDB FAQ RAG<br/>• Gemini LLM"]
        M2["M2 Operations Agent<br/>(Port 8005)<br/>• GBR Delay Model<br/>• pgvector Incident RAG<br/>• Control Room UI"]
        M3B["M3 Booking Agent<br/>(Port 8003)<br/>• Deterministic Inventory<br/>• Fare Engine<br/>• Cancellation Pipeline"]
        SEC["Security & Fraud Agent<br/>(Port 8004)<br/>• IsolationForest ML<br/>• Anomaly Scoring (<5ms)<br/>• Policy Grounding"]
        M4["M4 Maintenance Agent<br/>(Port 8006)<br/>• Asset Health Model<br/>• Equipment Manual RAG<br/>• Engineer Chatbot"]
    end

    subgraph Data["Shared Persistence & Source of Truth"]
        SB[("Supabase PostgreSQL<br/>• trains (Canonical Identity)<br/>• train_schedules (Capacity)<br/>• bookings & cancellations<br/>• pgvector embeddings<br/>• audit_events")]
        CH[("ChromaDB Index<br/>FAQ Vector Store (M1)")]
    end

    UP --> GW
    AP --> GW
    RC --> M1
    GW --> M3H
    M1 -->|POST /messages| M3H

    M3H -->|POST /internal/messages| M2
    M3H -->|POST /internal/messages| M3B
    M3H -->|POST /internal/messages| SEC
    M3H -->|POST /internal/messages| M4
    M3H -->|POST /internal/messages| M1

    M3B -.->|Evaluate Behavioral Risk| SEC

    M1 --> CH
    M1 --> SB
    M2 --> SB
    M3B --> SB
    M4 --> SB
```

---

## 🌐 Agent Port & Service Registry

| Port | Service Name | Role | Primary Interface / Documentation |
|---|---|---|---|
| **3000** | `unified-frontend` | Passenger & Admin Unified Web Gateway | [http://localhost:3000/user](http://localhost:3000/user) (User)<br>[http://localhost:3000/admin](http://localhost:3000/admin) (Admin) |
| **5173** | `m1-react-frontend` | Vite + React Passenger Chat App | [http://localhost:5173](http://localhost:5173) |
| **8001** | `passenger-agent` | M1 Conversational Assistant API | [http://localhost:8001/docs](http://localhost:8001/docs) (Swagger UI) |
| **8002** | `agent-hub` | M3 Central Communication Hub | [http://localhost:8002/docs](http://localhost:8002/docs) (Swagger UI) |
| **8003** | `booking-agent` | M3 Ticket Booking & Cancellation API | [http://localhost:8003/docs](http://localhost:8003/docs) (Swagger UI) |
| **8004** | `security-agent` | Security & Fraud Anomaly Detection API | [http://localhost:8004/docs](http://localhost:8004/docs) (Swagger UI) |
| **8005** | `operations-agent` | M2 Delay Prediction & Operations API | [http://localhost:8005](http://localhost:8005) (Control Room Dashboard)<br>[http://localhost:8005/admin](http://localhost:8005/admin) (Console) |
| **8006** | `maintenance-agent` | M4 Asset Intelligence & Diagnostics API | [http://localhost:8006](http://localhost:8006) (Asset Dashboard)<br>[http://localhost:8006/chat-ui](http://localhost:8006/chat-ui) (Engineer Chat) |

---

## 🗄️ Shared Train Identity Architecture

All agents resolve train identity against a single canonical Supabase `trains` table. **No agent invents, duplicates, or hallucinates train facts.**

```
                     SUPABASE POSTGRESQL
                              │
               ┌──────────────┴──────────────┐
               │  trains (PK: train_id)      │  train_schedules (FK: train_id)
               │  • train_name, route        │  • travel_date, departure/arrival
               │  • active, maintenance_flag │  • first_capacity, second_capacity
               └──────────────┬──────────────┘
                              │
      ┌────────────────┬──────┴─────────┬────────────────┐
      ▼                ▼                ▼                ▼
     M1               M2               M3               M4
 Passenger        Operations        Booking        Maintenance
Assistant           Agent            Agent            Agent
```

### Key Integration Rules:
1. **Canonical Train Validation**: M1, M2, and M3 check `trains` via `shared.train_repository` before answering inquiries or generating predictions.
2. **Maintenance → Booking Interlock**:
   - When an engineer flags an asset on M4 (`POST /api/flag-train`), M4 sets `maintenance_status = 'OUT_OF_SERVICE'` on the canonical `trains` record.
   - Any booking attempt on M3 for this train is instantly rejected with **HTTP 409 Conflict (`TRAIN_UNDER_MAINTENANCE`)**.
   - When M4 clears the flag (`maintenance_status = NULL`), M3 immediately allows reservations again.
3. **Shared Seat Inventory & Restorations**:
   - Available seats = `train_schedules.capacity` − count of active bookings in `bookings`.
   - When cancellations are approved, the booking status changes to `CANCELLED`, automatically and immediately restoring seat inventory for all agents.

---

## 🧩 Comprehensive Module Breakdown

### 🧑‍💼 Module 1 (M1) — Passenger Assistant Agent (`M1-passenger_assistant/`)
* **Trilingual NLU Pipeline (`nlu/`)**:
  - `lang_detect.py`: Unicode script range scanning for Sinhala (`\u0D80`–`\u0DFF`) and Tamil (`\u0B80`–`\u0BFF`), with `langdetect` fallback for English.
  - `intent_classifier.py`: Pattern and spaCy classification for `schedule_query`, `fare_query`, `delay_check`, `booking_request`, `complaint`, and `general`.
  - `ner_extractor.py`: Extracts origin/destination stations, departure/arrival times, train IDs, seat classes, and passenger counts.
* **Vector FAQ RAG (`rag/`)**:
  - ChromaDB index embedded with `sentence-transformers/all-MiniLM-L6-v2` across `schedules.md`, `fares.md`, and `policies.md`.
* **LLM Fallback & Generation**:
  - Google Gemini Flash (`gemini-3.5-flash-lite` / `gemini-1.5-flash`) for multi-turn responses, conversational polish, and complaint empathy.
* **Hub Dispatcher (`hub_client.py`)**:
  - Asynchronously constructs JWT-signed `AgentMessage` envelopes and queries M2 (delays) or M3 (bookings) through the Hub on Port 8002 with a 15-second bounded timeout.

---

### 🚦 Module 2 (M2) — Operations & Delay-Prediction Agent (`M2-operations-agent/`)
* **ML Delay Regressor (`ml/`)**:
  - `GradientBoostingRegressor` trained on 3,000 historical operations records.
  - Evaluated on test partition: **MAE = 2.24 minutes**, **RMSE = 2.88 minutes**, **R² = 0.8716**.
  - Direct exact historical observation match for known trains (returns recorded actual delays and causes before falling back to general regression).
* **Incident NLP Triage (`nlp/`)**:
  - Sanitization via Bleach against XSS and script injection.
  - 100% accuracy classification into `mechanical`, `signal_fault`, `staffing`, `track_obstruction`, `weather`.
  - 1-2 sentence operator brief generator.
* **IR / RAG Historical Precedent Retrieval (`rag/`)**:
  - Supabase `pgvector` (`match_incidents` RPC) embedding incident text via `all-MiniLM-L6-v2`, with offline TF-IDF vectorizer fallback.
  - Grounded explanation engine synthesizes the numerical delay prediction, model feature importances, and historical incidents into human-readable briefs.
* **Dashboards & Consoles**:
  - **Operations Control Room (`ui/index.html`)**: Real-time route delay heatmap, active risk alerts, level crossing monitors, interactive prediction drawer.
  - **Admin Operations Console (`admin_ui/index.html`)**: Model retraining triggers, audit logs, and incident queue management.

---

### 🛡️ Module 3 (M3) — Central Communication Hub & Booking Agent (`M3-Comunication-Hub&Booking-Agent/`)

#### 1. Central Agent Hub (`agent-hub/`)
* **Security & Auth (`auth/jwt_utils.py`)**: Verifies HMAC-SHA256 signatures, token expiration (`exp`), and subject identity (`sub`).
* **MCP Asynchronous Router (`router.py`)**: Resolves target URLs from `registry.py` and forwards `AgentMessage` payloads to `{service_url}/internal/messages`.
* **Tamper-Evident Audit Trail (`audit/`)**: Logs all incoming, routed, and rejected messages to Supabase `audit_events` (or SQLite fallback) with hashed identifiers.
* **Shared Schemas (`shared/schemas.py`)**: Pydantic v2 `AgentMessage` contract and `MemberCIntent` definitions.

#### 2. Booking & Reservation Agent (`booking-agent/`)
* **Deterministic Reservation Engine (`services/booking_service.py`)**: Zero LLM hallucination for financial or seat operations. Enforces real station schedules, class capacities, and fare tables.
* **Cancellation & Refund Pipeline (`services/cancellation_service.py`)**: Processes passenger refund requests, evaluates policy eligibility via NLP rules, and enqueues cases for administrative adjudication.

---

### 🔒 Security & Fraud Detection Agent (`security-agent/`)
* **Behavioral Anomaly Model (`fraud/model.py`)**:
  - Evaluates derived behavioral features: bookings in last 1m/10m/24h, cancellation ratios, rapid multi-route requests, duplicate seat attempts, and interval anomalies.
  - Scikit-Learn `IsolationForest` calibrated to output bounded anomaly risk index `[0.00, 1.00]`.
  - Outputs risk category (`LOW`, `MEDIUM`, `HIGH`) and policy action (`ALLOW`, `REVIEW`, `REJECT`).
  - Benchmarked at **99.17% Accuracy**, **100% Recall**, and **3.86 ms latency**.
* **Grounded Summary Engine (`fraud/llm_summary.py`)**:
  - Produces structured 4-part summaries citing railway reservation rules, risk factors, and recommended human actions.
* **Adjudication Feedback Loop**:
  - Admin reviewers record `CONFIRMED_FRAUD` or `FALSE_POSITIVE` labels to log true labels for future model retraining.

---

### 🔧 Module 4 (M4) — Maintenance & Asset Intelligence Agent (`M4-maintenance-agent/`)
* **Predictive Health Model (`ml/`)**:
  - Evaluates equipment age, days since service, fault history, sensor vibration, temperature, and hydraulic pressure to compute a 0–100 health score (`GREEN`, `AMBER`, `RED`).
  - Performance: **MAE = 3.76 points**, **R² = 0.8814**.
* **Technician Note NLP (`nlp/`)**:
  - Rule-based and LLM extraction of fault types, component IDs, telemetry readings, and corrective actions from free-text engineer logs.
* **Technical Manual RAG (`rag/`)**:
  - Indexes 5 comprehensive railway manuals: Diesel Locomotive Engine, Air Brake Systems, Bogie Inspection, Signalling & Interlocking, and Track Maintenance.
  - Achieves **100% Precision (P@1, P@3, P@5)** on benchmark troubleshooting queries.
* **Engineer Interactive Chatbot (`ui/chat.html`)**:
  - Web UI for depot technicians to query diagnostic steps and part specifications with exact page/section citations.

---

### 🌐 Unified Web Application & Portals (`frontend/`)
* **Unified Gateway Server (`serve.py`)**:
  - Runs on Port `3000` as the primary passenger and staff gateway.
  - Server-side JWT signing prevents database or secret exposure to client browsers.
* **Passenger Portal (`/user`)**:
  - Interactive live departures board with real-time delays.
  - Seat reservation wizard with class selection and fare calculation.
  - Digital Ticket issuance with downloadable PDF/HTML and QR verification code.
  - Embedded trilingual AI Passenger Chatbot.
* **Admin Control Center (`/admin`)**:
  - Unified operational command center integrating live feeds from M2 Operations, M3 Booking, M4 Maintenance, and Security Fraud Queues.

---

## 🔄 End-to-End Inter-Agent Message Flows

### Flow 1: Passenger Delay Query (`M1 -> Hub -> M2 -> Hub -> M1`)

```text
Passenger (User Chat)
       │  "Is the 14:35 Colombo Fort to Kandy train delayed?"
       ▼
[ M1 Passenger Assistant (Port 8001) ]
       │  NLU extracts: Intent=delay_check, Origin=Colombo Fort, Dest=Kandy, Train=YD-9337
       │  Generates JWT Token with sub=passenger-agent
       │  POST http://localhost:8002/messages (AgentMessage)
       ▼
[ M3 Communication Hub (Port 8002) ]
       │  Validates JWT & AgentMessage schema; logs to audit trail
       │  POST http://localhost:8005/internal/messages
       ▼
[ M2 Operations Agent (Port 8005) ]
       │  Matches train_id / route against historical observations & GBR model
       │  Retrieves incident RAG context from Supabase pgvector
       │  Generates grounded explanation (predicted_delay_minutes: 16.2)
       │  Returns AgentMessage (intent: delay_check_response)
       ▼
[ M3 Communication Hub (Port 8002) ]
       │  Routes response back to M1
       ▼
[ M1 Passenger Assistant (Port 8001) ]
       │  Formats conversational response citing delay time and reason
       ▼
Passenger Receives Answer (UI)
```

#### Envelope Example (`POST http://localhost:8002/messages`):
```json
{
  "message_id": "MSG-904128",
  "sender_agent": "passenger-agent",
  "receiver_agent": "operations-agent",
  "intent": "delay_check",
  "payload": {
    "route": "Colombo Fort - Kandy",
    "train_id": "YD-9337",
    "scheduled_time": "14:35",
    "query_text": "Is the 14:35 Colombo Fort to Kandy train delayed?"
  },
  "auth_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "timestamp": "2026-09-20T14:35:00Z"
}
```

---

### Flow 2: Ticket Booking & Fraud Scoring (`User -> Gateway -> Hub -> Booking -> Security`)

```text
Passenger submits reservation on Web Portal (Port 3000)
       │
       ▼
[ Unified Gateway (frontend/serve.py) ]
       │  Envelopes payload; signs inter-agent JWT
       │  POST http://localhost:8002/messages (intent: booking_request)
       ▼
[ M3 Communication Hub (Port 8002) ]
       │  Forwards to M3 Booking Agent
       ▼
[ M3 Booking Agent (Port 8003) ]
       │  1. Validates train is NOT flagged under maintenance
       │  2. Checks seat capacity in train_schedules
       │  3. Derives behavioral features (request velocity, rapid cancellation count)
       │  4. Calls Security Agent: POST http://localhost:8004/internal/fraud-score
       ▼
[ Security & Fraud Agent (Port 8004) ]
       │  IsolationForest computes risk_score (e.g., 0.08 -> LOW, ALLOW)
       │  Returns risk decision to Booking Agent
       ▼
[ M3 Booking Agent (Port 8003) ]
       │  Persists confirmed booking to Supabase bookings table
       │  Decrements available seat inventory
       │  Returns booking confirmation and ticket token
```

---

## 🛠️ Technology Stack

| Domain | Technologies |
|---|---|
| **Programming Language** | Python 3.11+, TypeScript / JavaScript (Node.js 18+) |
| **Backend Frameworks** | FastAPI, Uvicorn, Starlette, Pydantic v2 |
| **Machine Learning** | Scikit-Learn (`GradientBoostingRegressor`, `IsolationForest`), NumPy, Pandas, Joblib |
| **NLP & Language Models** | spaCy, Bleach, Google Gemini Flash (`gemini-3.5-flash-lite`), LangDetect, Sentence Transformers |
| **Vector DB & Information Retrieval** | Supabase PostgreSQL + `pgvector`, ChromaDB (Local), Scikit-Learn TF-IDF |
| **Database & Persistence** | Supabase (PostgreSQL 15), SQLAlchemy, SQLite (offline fallback) |
| **Security & Protocols** | PyJWT (HMAC-SHA256), Agent Communication Envelopes (MCP specification), CORS |
| **Frontend Technologies** | HTML5, Vanilla CSS3 (Glassmorphism design system), React, Vite, Chart.js, Lucide Icons |
| **Testing & Automation** | Pytest, HTTPX, Respx, PowerShell, Shell Scripts |

---

## 🚀 Installation & Environment Setup

### 1. Prerequisites
- **Python 3.11 or higher** installed and available on system PATH
- **Node.js 18 or higher** (for M1 React Frontend)
- **Git**
- Supabase account with PostgreSQL database and `pgvector` extension enabled

### 2. Clone Repository
```bash
git clone https://github.com/pasindi15/RailSence-AI.git
cd RailSence-AI
```

### 3. Environment Configuration (`.env`)
Create a `.env` file in the **workspace root** (refer to `.env.example`):
```ini
# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_your_key_here
SUPABASE_SECRET_KEY=sb_secret_your_key_here
DATABASE_URL=postgresql://postgres.your-project:password@aws-0-region.pooler.supabase.com:6543/postgres

# Inter-Agent Security & JWT
JWT_SECRET_KEY=railsense-super-secret-jwt-key
JWT_ALGORITHM=HS256

# Large Language Model Provider (M1 & Grounded Summaries)
LLM_PROVIDER=gemini-3.5-flash-lite
GEMINI_API_KEY=your_gemini_api_key_here
```

> [!IMPORTANT]
> **M1 Backend Environment Requirement**:  
> The M1 Passenger Assistant specifically loads configuration from `M1-passenger_assistant/backend/.env`.  
> Copy your root `.env` into that directory:
> ```powershell
> Copy-Item .env M1-passenger_assistant\backend\.env
> ```

---

### 4. Setting up Python Virtual Environments

#### Main Environment (Services M2, M3, Security, M4, Gateway):
```powershell
# In project root:
pip install -r M2-operations-agent/requirements.txt
pip install -r M3-Comunication-Hub&Booking-Agent/agent-hub/requirements.txt
pip install -r M3-Comunication-Hub&Booking-Agent/booking-agent/requirements.txt
pip install -r M4-maintenance-agent/requirements.txt
pip install -r M2-admin-dashboard/requirements-admin.txt
pip install psutil
```

#### Dedicated M1 Virtual Environment (Critical for ChromaDB):
> [!IMPORTANT]
> M1 uses a specific pre-built ChromaDB vector index in `.chroma/`. It must run in its own virtual environment inside `M1-passenger_assistant/backend/venv` to avoid binary len errors:
> ```powershell
> cd M1-passenger_assistant/backend
> python -m venv venv
> .\venv\Scripts\Activate.ps1
> pip install -r requirements.txt
> python -m spacy download en_core_web_sm
> cd ../..
> ```

#### M1 React Frontend:
```powershell
cd M1-passenger_assistant/frontend
npm install
cd ../..
```

---

## ⚡ How to Run the Platform

You can start the entire ecosystem using the automated scripts, or launch services individually.

### Option A: All-in-One Automated Startup (Recommended)

#### On Windows (PowerShell):
```powershell
.\start_all.ps1
```
*This launches each of the 8 services in its own terminal window with live colored output and health probes.*

#### On Windows (Batch):
```cmd
start_all.bat
```

#### On Linux / macOS:
```bash
chmod +x start_all.sh
./start_all.sh
```

---

### Option B: Orchestrated CLI Commands

Start backend services and frontend portals as background process trees with clean terminal multiplexing:

```bash
# Terminal 1: Launch all 6 backend agents together
python run_backend.py
# (or: npm run backend)

# Terminal 2: Launch unified frontend gateway (Port 3000)
python run_frontend.py
# (or: npm run frontend)

# Terminal 3 (Optional): Launch M1 React Frontend (Port 5173)
cd M1-passenger_assistant/frontend && npm run dev
```

---

### Option C: Manual Individual Service Launch

If you prefer starting individual agents for debugging:

| # | Service | Port | Terminal Launch Command |
|---|---|---|---|
| **1** | **M3 Agent Hub** | `8002` | `python -m uvicorn main:app --app-dir "M3-Comunication-Hub&Booking-Agent/agent-hub" --port 8002 --reload` |
| **2** | **Security Agent** | `8004` | `python -m uvicorn main:app --app-dir security-agent --port 8004 --reload` |
| **3** | **M3 Booking Agent** | `8003` | `python -m uvicorn main:app --app-dir "M3-Comunication-Hub&Booking-Agent/booking-agent" --port 8003 --reload` |
| **4** | **M2 Operations** | `8005` | `python -m uvicorn main:app --app-dir M2-operations-agent --port 8005 --reload` |
| **5** | **M4 Maintenance** | `8006` | `python -m uvicorn main:app --app-dir M4-maintenance-agent --port 8006 --reload` |
| **6** | **M1 Passenger** | `8001` | `& "M1-passenger_assistant/backend/venv/Scripts/python.exe" -m uvicorn main:app --app-dir M1-passenger_assistant/backend --port 8001 --reload` |
| **7** | **Unified Web Gateway**| `3000` | `python frontend/serve.py` |
| **8** | **M1 React App** | `5173` | `cd M1-passenger_assistant/frontend && npm run dev` |

---

## 🧪 Testing & Verification Suite

The repository includes a comprehensive testing suite verifying single-service health, cross-agent message routing, and full end-to-end integration:

### 1. Full System End-to-End Integration Test
Validates all 6 backend agents, the Web Gateway, User/Admin portals, and live delay/booking message flows:
```bash
python test_full_system_integration.py
```

### 2. Portal & Gateway Verification
Validates that Port 3000 serves all passenger and admin portal routes correctly:
```bash
python test_portals.py
# (or: npm run test:portals)
```

### 3. Cross-Agent Integration Tests
```bash
# M1 -> M2 Delay Prediction & Registry Check
python scripts/test_m1_m2_integration.py

# M3 Booking Reservation & Cancellation Scenarios
python scripts/test_m3_booking_integration.py

# Full M1 + M2 + M3 + M4 Cross-Agent Workflow
python scripts/test_m4_cross_agent_integration.py
```

### 4. Model Benchmarking & Evaluation Scripts
Regenerates evaluation tables and metrics from raw datasets:
```bash
# Security & Fraud IsolationForest Benchmark
python security-agent/evaluate_model.py

# M2 Operations Delay Regressor & Incident NLP Evaluation
python M2-operations-agent/ml/train_delay_model.py
python M2-operations-agent/nlp/evaluate_nlp.py
python M2-operations-agent/evaluation/rag/evaluate_retrieval.py

# M4 Asset Health Regressor & Manual RAG Evaluation
python M4-maintenance-agent/ml/train_health_model.py
python M4-maintenance-agent/nlp/evaluate_nlp.py
python M4-maintenance-agent/evaluation/rag/evaluate_retrieval.py
```

---

## 📁 Repository Directory Structure

```text
RailSence-AI/
├── .env.example                               # Environment template
├── start_all.ps1                              # All-in-one PowerShell orchestrator
├── start_all.bat                              # All-in-one Windows batch script
├── start_all.sh                               # All-in-one Unix shell script
├── run_backend.py                             # Single-command orchestrator for 6 agents
├── run_frontend.py                            # Single-command orchestrator for Port 3000
├── test_full_system_integration.py            # Complete end-to-end integration test
├── test_portals.py                            # Portal routes & API test suite
│
├── frontend/                                  # Unified Web Gateway (Port 3000)
│   ├── serve.py                               # FastAPI web gateway & proxy server
│   ├── index.html                             # Main landing portal
│   ├── user.html                              # Passenger Portal (/user)
│   └── admin.html                             # Admin Control Center (/admin)
│
├── M1-passenger_assistant/                    # Module 1 (Port 8001 / Port 5173)
│   ├── backend/                               # FastAPI passenger backend
│   │   ├── nlu/                               # Trilingual intent & entity extractors
│   │   ├── rag/                               # ChromaDB FAQ retrieval engine
│   │   ├── .chroma/                           # Pre-built ChromaDB vector storage
│   │   ├── hub_client.py                      # Outbound MCP message client
│   │   └── main.py                            # Port 8001 service entrypoint
│   └── frontend/                              # Vite + React Passenger Chat UI (Port 5173)
│
├── M2-operations-agent/                       # Module 2 (Port 8005)
│   ├── ml/                                    # GBR delay prediction model & training
│   ├── nlp/                                   # Incident classifier & summarizer
│   ├── rag/                                   # Supabase pgvector incident retrieval
│   ├── ui/                                    # Operations Control Room (index.html)
│   ├── admin_ui/                              # Admin Console (index.html)
│   ├── data/operations_history.csv            # 3,000 historical operations records
│   └── main.py                                # Port 8005 service entrypoint
│
├── M3-Comunication-Hub&Booking-Agent/         # Module 3 (Port 8002 & Port 8003)
│   ├── agent-hub/                             # Central Communication Hub (Port 8002)
│   │   ├── auth/                              # JWT signature verification
│   │   ├── router.py                          # Asynchronous envelope router
│   │   ├── registry.py                        # Service URL registry
│   │   ├── audit/                             # Supabase/SQLite audit logging
│   │   └── main.py                            # Port 8002 service entrypoint
│   └── booking-agent/                         # Ticket Booking Agent (Port 8003)
│       ├── services/                          # Deterministic booking & cancellation logic
│       ├── cancellation/                      # NLP cancellation policy evaluation
│       └── main.py                            # Port 8003 service entrypoint
│
├── security-agent/                            # Security & Fraud Agent (Port 8004)
│   ├── fraud/                                 # IsolationForest model & grounded summary
│   ├── evaluate_model.py                      # Benchmarking script (Accuracy/Latency)
│   └── main.py                                # Port 8004 service entrypoint
│
├── M4-maintenance-agent/                      # Module 4 (Port 8006)
│   ├── ml/                                    # Asset predictive health model
│   ├── nlp/                                   # Technician note NLP extractor
│   ├── rag/                                   # Technical manual vector retriever
│   ├── ui/                                    # Asset Health Dashboard & Engineer Chat
│   ├── data/assets_history.csv                # 600 asset telemetry records
│   ├── data/manuals/                          # 5 indexed equipment manuals
│   └── main.py                                # Port 8006 service entrypoint
│
├── shared/                                    # Shared schemas & database models
│   ├── schemas.py                             # AgentMessage & intent definitions
│   └── train_repository.py                    # Canonical train resolution helper
└── scripts/                                   # Specialized cross-agent test scripts
```

---

## 📜 Academic Attribution & License

- **Course**: IT3041 – Information Retrieval & Web Analytics  
- **Year & Semester**: Year 3, Semester 2  
- **Institution**: Sri Lanka Institute of Information Technology (SLIIT)  
- **Project**: RailSense AI — Multi-Agent Railway Intelligence Ecosystem  
- **License**: Academic Educational Project — All Rights Reserved  
