# 🚆 RailSense AI — Agentic AI Platform for Railway Operations

> **IT3041 – Information Retrieval & Web Analytics**  
> Comprehensive Multi-Agent Railway Intelligence System integrating Large Language Models (LLMs), Natural Language Processing (NLP), Information Retrieval (IR/RAG), Machine Learning, Security, and MCP-Style Agent Communication Protocols.

---

## 📌 Executive Summary

**RailSense AI** is an enterprise-grade agentic artificial intelligence platform designed to revolutionize railway network management, passenger experience, predictive maintenance, ticket booking, and operational reliability.

The platform comprises **four autonomous, specialized AI agents** coordinated through a centralized **Agent Communication Hub**:

1. 🧑‍💼 **Module 1 (M1) — Passenger Assistant Agent**: Multilingual conversational AI (Sinhala / Tamil / English), RAG FAQ retrieval, schedule/fare intelligence, delay checking, booking dispatch, and complaint escalation.
2. 🚦 **Module 2 (M2) — Operations & Delay-Prediction Agent**: Machine learning delay regressor, historical incident pgvector/TF-IDF RAG, plain-language grounded prediction explanations, incident NLP triage, and live Operations Control Room dashboard.
3. 🛡️ **Module 3 (M3) — Central Communication Hub & Booking Agent**: Centralized JWT authentication, schema validation, audit trail, MCP envelope routing, deterministic ticket reservation engine, and human-in-the-loop cancellation workflow.
4. 🔧 **Module 4 (M4) — Maintenance & Asset Intelligence Agent**: Predictive asset health scoring, sensor telemetry analysis, technician note NLP extraction, technical manual RAG search, and maintenance engineer chatbot.

---

## 🏗️ System Architecture & Inter-Agent Communication

All inter-agent traffic is **hub-mediated** using standard MCP-style JSON envelopes (`AgentMessage`). No agent directly invokes another agent's private endpoints.

```
                                  Passenger User
                                         │
                                         ▼
                             [ M1 Passenger Assistant ]
                                    (Port 8001)
                                         │
                                         │  POST /messages (AgentMessage Envelope)
                                         ▼
                        [ M3 Agent Communication Hub ]
                                    (Port 8002)
                                         │
          ┌──────────────────────────────┼──────────────────────────────┐
          │                              │                              │
          ▼                              ▼                              ▼
[ M2 Operations Agent ]      [ M3 Booking Agent ]       [ M4 Maintenance Agent ]
     (Port 8005)                    (Port 8003)                    (Port 8006)
 ├─ ML Delay Regressor           ├─ Ticket Reservation          ├─ Predictive Health Model
 ├─ Historical Incident RAG      ├─ Seat Inventory              ├─ Technical Manual RAG
 ├─ NLP Incident Triage          ├─ Cancellation Workflow       ├─ Technician Note NLP
 └─ Control Room UI              └─ Audit & Admin DB            └─ Maintenance & Chat UI
```

---

## 🌐 Agent Port & Service Registry

| Module | Logical Service Name | Port | Description | Primary Frontend UI |
|---|---|---|---|---|
| **M1** | `passenger-agent` | `8001` | Conversational Passenger Assistant | `http://localhost:8001` (React Chat UI) |
| **M3** | `agent-hub` | `8002` | Central Communication Hub & Router | `http://localhost:8002/docs` (Swagger UI) |
| **M3** | `booking-agent` | `8003` | Ticket Booking & Cancellation Agent | `http://localhost:8003/docs` (Swagger UI) |
| **M2** | `operations-agent` | `8005` | Operations & Delay Prediction Agent | `http://localhost:8005` (Control Room Dashboard) |
| **M4** | `maintenance-agent` | `8006` | Maintenance & Asset Intelligence Agent | `http://localhost:8006` (Asset Dashboard) & `/chat-ui` |

---

## 🧩 Comprehensive Module Breakdown

---

### 🧑‍💼 Module 1 (M1) — Passenger Assistant Agent

#### Purpose
Provides intelligent, multi-script conversational assistance for passengers across web and mobile interfaces.

#### Backend Implementation (`M1-passenger_assistant/backend/`)
- **FastAPI Service (`main.py`)**: Runs on port `8001`. Endpoints: `/chat`, `/chat/{session_id}/history`, `/feedback`, `/health`.
- **Language Detection (`nlu/lang_detect.py`)**: Unicode script scanning for Sinhala (`si`) and Tamil (`ta`), with `langdetect` fallback for English (`en`).
- **Intent Classification (`nlu/intent_classifier.py`)**: spaCy/pattern classifier detecting `schedule_query`, `fare_query`, `delay_check`, `booking_request`, `complaint`, and `general`.
- **Named Entity Extraction (`nlu/ner_extractor.py`)**: Extracts origin/destination stations, departure/arrival times, train IDs, seat classes, and passenger counts.
- **RAG FAQ Retriever (`rag/retriever.py`)**: ChromaDB vector index over railway FAQ documents (`schedules.md`, `fares.md`, `rules.md`).
- **Hub Dispatcher (`hub_client.py`)**: Constructs JWT-signed `AgentMessage` envelopes and dispatches queries to M3 Hub (`http://localhost:8002/messages`).

#### Frontend Implementation (`M1-passenger_assistant/frontend/`)
- Modern glassmorphism React + Vite application (`http://localhost:8001`).
- Dynamic chat bubble stream, quick action buttons, language indicators, session history sidebar, feedback rating modal, and grounded source citations.

---

### 🚦 Module 2 (M2) — Operations & Delay-Prediction Agent

#### Purpose
Provides real-time train delay predictions, incident analysis, historical precedent retrieval, delay alerting, and operational monitoring.

#### Backend Implementation (`M2-operations-agent/`)
- **FastAPI Service (`main.py`)**: Runs on port `8005`. Endpoints: `/predict-delay`, `/route-status/{id}`, `/incident-report`, `/internal/messages`, `/hub/message`, `/api/dashboard`, `/api/operations`, `/api/events`, `/health`.
- **ML Delay Regressor (`ml/predict.py` & `ml/train_delay_model.py`)**: Trained `GradientBoostingRegressor` on historical operations data (`MAE = 2.239 min`, `RMSE = 2.876 min`, `R² = 0.8716`). Feature importances exported to `feature_importances.json`.
- **Incident NLP Triage (`nlp/classify_incident.py` & `nlp/summarize_incident.py`)**: HTML/Script sanitization via Bleach/Pydantic, 100% accuracy rule-based and LLM incident classifier (`mechanical`, `signal_fault`, `staffing`, `track_obstruction`, `weather`), and condensed 1-2 sentence operator briefs.
- **IR/RAG Historical Retrieval (`rag/incident_retriever.py`)**: Sentence-Transformers `all-MiniLM-L6-v2` embeddings stored in Supabase pgvector (`match_incidents` RPC) with local TF-IDF fallback.
- **Grounded Explanation Layer (`rag/explanation.py`)**: Combines numerical delay prediction + top model feature importances + top 3 retrieved historical incidents intoplain-language operator explanations.
- **Alert & Event Publisher (`hub_client.py`)**: Automatically publishes `delay_alert` events to M3 Hub and Upstash Redis whenever predicted delay is $\ge 5.0$ minutes.
- **Audit Logging (`data/audit_log.jsonl` & `supabase_store.py`)**: Audit trail for all predictions, triage actions, and Hub requests.
- **Admin Dashboard Backend (`admin/admin_router.py` & `admin_db.py`)**: Admin CRUD routes for incident reports and model retraining logs.

#### Frontend Dashboards (`M2-operations-agent/ui/` & `admin_ui/`)
- **Operations Control Room (`ui/index.html`)**: Served at `http://localhost:8005`. Features live route heatmaps, hourly delay pressure graphs, active risk zones, level crossing monitors, interactive prediction drawer, incident triage modal, evaluation panels, and live event feed.
- **Admin Console (`admin_ui/index.html`)**: Served at `http://localhost:8005/admin`. Provides incident review queues and model version management.

---

### 🛡️ Module 3 (M3) — Central Communication Hub & Booking Agent

#### Purpose
Acts as the security gateway, message router, audit logger, and ticket reservation authority for the entire RailSense platform.

#### Backend Implementation (`M3-Comunication-Hub&Booking-Agent/`)

##### 1. Central Agent Hub (`agent-hub/`)
- **FastAPI Service (`main.py`)**: Runs on port `8002`. Endpoints: `POST /messages`, `GET /health`.
- **JWT Verification (`auth/jwt_utils.py`)**: Verifies signature, expiration (`exp`), and subject matching (`sub`) using PyJWT.
- **Agent Registry (`registry.py`)**: Maintains logical name to base URL mapping (`passenger-agent`, `booking-agent`, `security-agent`, `operations-agent`, `maintenance-agent`).
- **Asynchronous Router (`router.py`)**: Forwards validated `AgentMessage` envelopes to `{base_url}/internal/messages` via `httpx.AsyncClient` with timeout handling and status code mapping.
- **Audit Trail (`audit/service.py` & `hub_database.py`)**: Records pre-routing (`AUTHENTICATED`), success (`ROUTED`), or failure (`REJECTED`/`FAILED`) records to SQLite/PostgreSQL.
- **Shared Schemas (`shared/schemas.py`)**: Pydantic v2 `AgentMessage` envelope and `MemberCIntent` enum supporting all system intents (`booking_request`, `cancel_booking`, `delay_check`, `delay_check_response`, `delay_alert`, `issue_report`, `incident_report`, `ack`).

##### 2. Booking & Reservation Agent (`booking-agent/`)
- **FastAPI Service (`main.py`)**: Runs on port `8003`. Endpoints: `POST /internal/messages`, `GET /bookings/{ref}`, `GET /cancellations`, `GET /health`.
- **Deterministic Booking Engine (`services/booking_service.py`)**: Processes `booking_request` intents. Checks seat availability and calculates fares using database rules (never LLM hallucinated).
- **Cancellation Approval Pipeline (`services/cancellation_service.py`)**: Receives `cancel_booking` requests, generates NLP eligibility recommendations, and queues cases for human admin final approval.

---

### 🔧 Module 4 (M4) — Maintenance & Asset Intelligence Agent

#### Purpose
Monitors rolling stock and track assets, predicts equipment failure risks, analyzes technician notes, and searches technical manuals.

#### Backend Implementation (`M4-maintenance-agent/`)
- **FastAPI Service (`main.py`)**: Runs on port `8006`. Endpoints: `/asset-health`, `/asset-status/{id}`, `/maintenance-report`, `/manual-search`, `/chat`, `/internal/messages`, `/hub/message`, `/api/dashboard`, `/api/assets`, `/health`.
- **Predictive Health Model (`ml/predict.py`)**: Evaluates asset telemetry (days since service, 30-day fault count, sensor vibration/temperature/pressure) to output a health score (0–100) and status (`GREEN`, `AMBER`, `RED`).
- **Technician Note NLP (`nlp/extract_notes.py` & `nlp/summarize_report.py`)**: Extracts fault types, affected components, measurements, and actions taken from raw technician logs.
- **Equipment Manual RAG (`rag/manual_retriever.py`)**: Searches indexed equipment manuals (`diesel_engine_manual.md`, `bogie_manual.md`, `signalling_manual.md`) using MiniLM embeddings / pgvector with local TF-IDF fallback.
- **Engineer RAG Chatbot (`rag/chatbot.py`)**: Conversational Q&A interface for maintenance technicians to query technical manuals.
- **Alert Publishing (`hub_client.py`)**: Publishes `maintenance_alert` events for `RED` status assets to Hub and Upstash Redis.

#### Frontend Dashboards (`M4-maintenance-agent/ui/`)
- **Asset Intelligence Dashboard (`ui/index.html`)**: Served at `http://localhost:8006`. Displays fleet health distribution, asset risk cards, telemetry gauges, and recent maintenance logs.
- **Maintenance Engineer Chatbot (`ui/chat.html`)**: Served at `http://localhost:8006/chat-ui`. Interactive manual search and troubleshooting assistant for field engineers.

---

## 🔄 End-to-End Inter-Agent Message Envelopes

### 1. Passenger Delay Query (`M1 -> M3 Hub -> M2 -> M3 Hub -> M1`)

#### Request Envelope (`POST http://localhost:8002/messages`)
```json
{
  "message_id": "MSG-2001",
  "sender_agent": "passenger-agent",
  "receiver_agent": "operations-agent",
  "intent": "delay_check",
  "payload": {
    "route": "Colombo Fort - Kandy",
    "train_id": "PM-4082",
    "stations": ["Colombo Fort", "Kandy"],
    "raw_text": "Is the 14:35 train from Colombo Fort to Kandy delayed?"
  },
  "auth_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "timestamp": "2026-09-12T14:35:00Z"
}
```

#### Response Payload (`delay_check_response`)
```json
{
  "message_id": "MSG-2001",
  "sender_agent": "operations-agent",
  "receiver_agent": "passenger-agent",
  "intent": "delay_check_response",
  "payload": {
    "predicted_delay_minutes": 9.0,
    "confidence": "medium",
    "explanation": "Expect approximately 9.0 minutes of delay on Colombo Fort - Kandy. Historical congestion and light rain are forecast. A similar signal fault was recorded at Kandy with a 9.4-minute delay.",
    "reason": "Expect approximately 9.0 minutes of delay on Colombo Fort - Kandy. Historical congestion and light rain are forecast.",
    "similar_incident": "Signal failure reported near Kandy, historical delay 9.4 min",
    "similar_past_incidents": [
      "Signal failure reported near Kandy, historical delay 9.4 min"
    ],
    "top_contributing_features": [
      {"feature": "incident_type_none", "importance": 0.7390},
      {"feature": "weather_light_rain", "importance": 0.0390}
    ],
    "model_version": "phase2-gbr-v1",
    "retrieval_method": "supabase_pgvector",
    "explanation_method": "template_grounded"
  },
  "timestamp": "2026-09-12T14:35:02Z"
}
```

---

### 2. Ticket Booking Request (`M1 -> M3 Hub -> M3 Booking Agent`)

#### Request Envelope (`POST http://localhost:8002/messages`)
```json
{
  "message_id": "MSG-2002",
  "sender_agent": "passenger-agent",
  "receiver_agent": "booking-agent",
  "intent": "booking_request",
  "payload": {
    "from_station": "Colombo Fort",
    "to_station": "Kandy",
    "travel_date": "2026-10-15",
    "train_id": "PM-4082",
    "seat_class": "Second Class",
    "passenger_count": 2
  },
  "auth_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "timestamp": "2026-09-12T14:36:00Z"
}
```

---

## 🛠️ Technology Stack

| Domain | Technologies |
|---|---|
| **Core Backend** | Python 3.11+, FastAPI, Uvicorn, Pydantic v2, Starlette |
| **Machine Learning** | Scikit-Learn, Pandas, NumPy, Joblib |
| **NLP & LLM** | spaCy, Bleach, Anthropic Claude API, Google Gemini Flash, Sentence Transformers |
| **Vector DB & RAG** | Supabase PostgreSQL + `pgvector`, ChromaDB, TF-IDF (Local Fallback) |
| **Messaging & Cache** | Upstash Redis, HTTPX Async Client, JWT Authentication (PyJWT) |
| **Frontend UI** | Vanilla CSS3, HTML5, React, Vite, Glassmorphism Design System, Chart.js |
| **Deployment** | Docker, Docker Compose, PowerShell |

---

## 🚀 Installation & Setup Guide

### 1. Prerequisites
- Python 3.11+
- Node.js 18+ (for M1 React frontend)
- Git & Docker Compose (optional)

### 2. Clone Repository
```bash
git clone https://github.com/pasindi15/RailSence-AI.git
cd RailSence-AI
```

### 3. Environment Configuration
Create a `.env` file in the root directory (or copy `.env.example`):
```ini
JWT_SECRET_KEY=railsense-super-secret-jwt-key
JWT_ALGORITHM=HS256

SUPABASE_URL=https://your-supabase-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-key

ANTHROPIC_API_KEY=your-anthropic-key
GEMINI_API_KEY=your-gemini-key
```

---

## ⚡ Running Services Locally

You can launch each agent in separate terminal windows:

### 1. Launch M3 Central Communication Hub (Port 8002)
```powershell
python -m uvicorn main:app --app-dir "M3-Comunication-Hub&Booking-Agent/agent-hub" --reload --port 8002
```

### 2. Launch M3 Booking & Reservation Agent (Port 8003)
```powershell
python -m uvicorn main:app --app-dir "M3-Comunication-Hub&Booking-Agent/booking-agent" --reload --port 8003
```

### 3. Launch M2 Operations Agent (Port 8005)
```powershell
python -m uvicorn main:app --app-dir M2-operations-agent --reload --port 8005
```

### 4. Launch M4 Maintenance Agent (Port 8006)
```powershell
python -m uvicorn main:app --app-dir M4-maintenance-agent --reload --port 8006
```

### 5. Launch M1 Passenger Assistant Backend (Port 8001)
```powershell
python -m uvicorn main:app --app-dir M1-passenger_assistant/backend --reload --port 8001
```

---

## 📊 Model Training & Evaluation Execution

To train ML models and regenerate committed evaluation metrics:

### Train M2 Operations Delay Model
```powershell
python M2-operations-agent/ml/train_delay_model.py
```

### Evaluate M2 NLP & RAG Performance
```powershell
python M2-operations-agent/nlp/evaluate_nlp.py
python M2-operations-agent/evaluation/rag/evaluate_retrieval.py
```

### Run End-to-End Multi-Agent Integration Tests
```powershell
python test_integration.py
```

---

## 📜 Academic Attribution & License

- **Course**: IT3041 – Information Retrieval & Web Analytics  
- **Institution**: Sri Lanka Institute of Information Technology (SLIIT)  
- **License**: Academic Educational Project  
