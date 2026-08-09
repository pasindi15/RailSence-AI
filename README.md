# 🚆 RailSense AI
## Agentic AI System for Intelligent Railway Operations

> **IT3041 – Information Retrieval & Web Analytics**  
> Multi-Agent AI System integrating LLMs, NLP, Information Retrieval, Security, and Agent Communication Protocols.

---

# 📌 Overview

**RailSense AI** is an agentic artificial intelligence platform designed to transform railway operations through a network of cooperating AI agents.

The system consists of **four autonomous AI agents** coordinated through a centralized **MCP-style Agent Communication Hub**.

Each agent independently provides specialized intelligence while collaborating with other agents to solve complex railway problems.

### Operations Agent Progress

The Operations Agent has completed Phases 1–4:

- Phase 1: FastAPI service, synthetic operations dataset, and stable API contract
- Phase 2: Gradient Boosting delay model with held-out evaluation metrics
- Phase 3: Sanitized incident summarization and classification
- Phase 4: Historical incident retrieval and grounded prediction explanations

Phase 5 covers Hub integration, rate limiting, audit logging, and the complete
multi-agent production dashboard.

### 🚉 Core AI Agents

| Agent | Responsibility |
|---|---|
| 🧑‍💼 Passenger Assistant Agent | Passenger conversations, multilingual NLP, RAG-based assistance |
| 🚦 Operations Agent | Delay prediction, incident intelligence, operational analytics |
| 🛡️ Security Agent | Authentication, fraud detection, encryption, system security |
| 🔧 Maintenance Agent | Predictive maintenance, equipment intelligence, manual-based RAG |

---

# 🎯 Project Objective

RailSense AI aims to demonstrate how **agentic AI systems** can improve railway services by combining:

- Large Language Models (LLMs)
- Natural Language Processing (NLP)
- Information Retrieval (IR)
- Retrieval Augmented Generation (RAG)
- Machine Learning Prediction Models
- Secure Agent Communication
- Responsible AI Practices

The system behaves like a real AI-powered railway management platform rather than a simple chatbot.

---

# 🏗️ System Architecture


```

```
                Passenger User
                     |
                     |
             Passenger Agent
                     |
                     |
            Agent Communication Hub
                     |
    ---------------------------------------
    |                  |                  |
    |                  |                  |
```

Operations Agent   Security Agent   Maintenance Agent

```
    |
    |
```

Delay Prediction
Incident Analysis
Maintenance Correlation

```

---

# 🤖 Agent Architecture

## 🧑‍💼 Passenger Assistant Agent

### Purpose

Provides intelligent passenger interaction through conversational AI.

### Responsibilities

- Multilingual chatbot (Sinhala / Tamil / English)
- Intent classification
- Named Entity Recognition
- Railway FAQ retrieval
- Schedule and fare information
- Delay checking through Operations Agent
- Complaint forwarding to Maintenance Agent

### AI Components

| Component | Technology |
|-|-|
| NLP | spaCy / LLM Function Calling |
| Language Detection | langdetect |
| Retrieval | ChromaDB |
| Embeddings | Sentence Transformers |
| Generation | LLM + RAG |

---

## 🚦 Operations & Delay Prediction Agent

### Purpose

Provides intelligent railway operation monitoring.

### Responsibilities

- Train delay prediction
- Incident analysis
- Historical incident retrieval
- Operational dashboard
- Delay alert publishing

### AI Components

| Component | Technology |
|-|-|
| ML Model | Random Forest / Gradient Boosting |
| Explainability | Feature Importance |
| NLP | Incident Summarization |
| IR / RAG | MiniLM embeddings, Supabase pgvector, local TF-IDF fallback |
| Explanation | Grounded template or optional Claude API |

### Operations Agent Phase 4 Flow

The `/predict-delay` workflow combines the Phase 2 model with historical
evidence:

1. Build a retrieval query from route, station, weather, and incident type.
2. Retrieve the top three similar historical incident records.
3. Combine the prediction, top model features, and retrieved incidents.
4. Return a plain-language explanation with cited precedent.

The local TF-IDF index works without cloud credentials, which keeps local
demos reproducible. When `SUPABASE_URL` and `SUPABASE_KEY` are configured,
the API uses the Supabase pgvector `match_incidents` function. When
`ANTHROPIC_API_KEY` is configured, Claude composes the explanation using only
the supplied prediction and retrieved evidence.

Example `/predict-delay` response:

```json
{
      "route": "Colombo Fort - Kandy",
      "train_id": "PM-4082",
      "predicted_delay_minutes": 14.2,
      "confidence": "medium",
      "explanation": "Expect approximately 14.2 minutes of delay on Colombo Fort - Kandy. A similar signal fault was recorded at Kandy with a 14.1-minute delay.",
      "top_contributing_features": [
            {"feature": "incident_type_none", "importance": 0.7390},
            {"feature": "incident_type_mechanical", "importance": 0.0708},
            {"feature": "weather_clear", "importance": 0.0390}
      ],
      "similar_past_incidents": [
            "signal fault at Kandy on Colombo Fort - Kandy ... historical delay 14.1 min"
      ],
      "model_version": "phase2-gbr-v1",
      "retrieval_method": "local_tfidf",
      "explanation_method": "template_grounded"
}
```

Example:

```

Prediction:

Train:
Colombo Fort → Kandy

Expected Delay:
9 minutes

Reason:
Historical congestion + weather conditions

Similar Incident:
Signal failure occurred on same route previously

```

---

# 🛡️ Security & Fraud Agent

## Purpose

Provides secure communication and intelligent threat detection.

### Responsibilities

- Central Agent Hub ownership
- JWT authentication
- Encryption management
- Fraud detection
- Audit logging
- Security monitoring

### Security Features

✅ JWT authentication  
✅ AES encryption  
✅ Password hashing  
✅ Input sanitization  
✅ API validation  
✅ Audit trail  
✅ Vulnerability checking  


### Fraud Detection

Model:

```

Isolation Forest

```

Detects:

- Unusual ticket purchases
- Multiple bookings within seconds
- Impossible travel patterns
- Suspicious user behaviour

---

# 🔧 Maintenance & Asset Intelligence Agent

## Purpose

Provides AI-powered railway asset monitoring.

### Responsibilities

- Predictive maintenance
- Sensor analysis
- Equipment health scoring
- Maintenance recommendation
- Technical manual RAG search


### AI Components

| Component | Technology |
|-|-|
| Prediction | Health scoring model |
| NLP | Technician note extraction |
| RAG | Equipment manuals |
| LLM | Maintenance reports |


Example:

```

Asset:

Train Engine #204

Health:

AMBER

Recommendation:

Inspect braking system within 14 days.

Source:
Maintenance Manual Section 4.2

````

---

# 🔄 Agent Communication Hub

The Hub acts as the central communication layer.

Every agent communicates through the Hub using a lightweight MCP-style JSON protocol.

---

## Message Structure

Example:

```json
{
 "message_id":"b7e1-uuid",
 "sender_agent":"passenger-agent",
 "receiver_agent":"operations-agent",
 "intent":"delay_check",

 "payload":{
    "route":"Colombo Fort - Kandy",
    "train_id":"PM-4082"
 },

 "auth_token":"JWT_TOKEN",

 "timestamp":"2026-09-10T13:58:12"
}
````

---

# 🔁 Agent Interaction Example

## Passenger asks:

> "Is the 14:35 Colombo-Kandy train delayed?"

### Workflow:

```
1. Passenger Agent
      |
      | NLP extracts:
      | route + time + intent
      |
      ↓

2. Agent Hub

      |
      | JWT verification
      |
      ↓

3. Operations Agent

      |
      | ML Prediction
      | Incident Retrieval
      | LLM Explanation
      |
      ↓

4. Response returned

      |
      ↓

Passenger receives:

"The train is expected to delay by 9 minutes due to historical congestion."
```

---

# 🎨 User Interface Design

RailSense follows a unified **Light Rail Design System**.

## Theme

* Light glassmorphism
* High contrast accent colors
* Modern enterprise dashboard style

## Agent Colors

| Agent       | Color  |
| ----------- | ------ |
| Passenger   | Blue   |
| Operations  | Amber  |
| Security    | Rose   |
| Maintenance | Purple |

---

# 🖥️ Dashboards

## Passenger Assistant

Features:

* Chat interface
* Quick actions
* Multilingual support
* Source citations

## Operations Dashboard

Features:

* Active trains
* Delay statistics
* Route heatmaps
* Incident timeline
* Prediction confidence

The current Operations Agent dashboard is served by FastAPI at
`http://localhost:8001/`. It already supports incident processing and
grounded delay prediction with historical precedent. Route heatmaps, live
statistics, and Hub events are Phase 5 additions.

## Security Console

Features:

* User sessions
* Fraud alerts
* Audit logs
* Risk explanation

## Maintenance Console

Features:

* Asset health cards
* Maintenance schedule
* Manual search
* AI recommendations

---

# 📂 Repository Structure

```
RailSense-AI/

│
├── agent-hub/
│   ├── main.py
│   ├── auth/
│   ├── schema.py
│   └── audit_log.py
│
├── passenger-agent/
│   ├── main.py
│   ├── nlu/
│   ├── rag/
│   ├── prompts/
│   └── frontend/
│
├── operations-agent/
│   ├── main.py
│   ├── ml/
│   ├── nlp/
│   ├── rag/
│   └── frontend/
│
├── security-agent/
│   ├── main.py
│   ├── fraud/
│   ├── crypto/
│   └── frontend/
│
├── maintenance-agent/
│   ├── main.py
│   ├── predictive/
│   ├── rag/
│   └── frontend/
│
├── docker-compose.yml
│
├── docs/
│
└── README.md

```

---

# 🧰 Technology Stack

## Backend

* Python
* FastAPI
* REST APIs

## AI / ML

* Large Language Models
* LangChain
* Sentence Transformers
* Scikit-learn
* spaCy

## Vector Database

* Supabase Postgres + pgvector for shared incident retrieval
* Local TF-IDF fallback for offline Operations Agent demos
* ChromaDB remains available for Passenger Agent retrieval where appropriate

## Frontend

* React / Next.js
* Tailwind CSS

## Security

* JWT
* AES Encryption
* bcrypt

## Deployment

* Docker
* Docker Compose

---

# 🔐 Responsible AI Implementation

| Principle       | Implementation                |
| --------------- | ----------------------------- |
| Fairness        | Sinhala/Tamil/English testing |
| Explainability  | Prediction reasons            |
| Transparency    | AI disclosure                 |
| Privacy         | Encryption & access control   |
| Human Oversight | Escalation paths              |
| Bias Analysis   | Dataset evaluation            |

---

# 📊 Evaluation Metrics

## NLP Evaluation

* Intent classification accuracy
* NER accuracy
* Language detection accuracy

## Retrieval Evaluation

* Precision@3
* Relevant document retrieval
* Phase 4 evidence: `/predict-delay` returns three retrieved incident citations
      plus the `retrieval_method` used (`local_tfidf` or `supabase_pgvector`)
* Measured local TF-IDF proxy on 150 held-out queries: P@1 = 1.0000,
      P@3 = 1.0000, P@5 = 1.0000
* Six-query paraphrase stress test: top-1 accuracy = 0.6667 and top-3 recall
      = 0.6667; this is a small robustness check, not a representative benchmark

Regenerate the retrieval evidence with:

```powershell
python M2-operations-agent/evaluation/rag/evaluate_retrieval.py
```

## ML Evaluation

Delay Prediction:

* MAE
* RMSE

Fraud Detection:

* Detection rate
* False positive analysis

---

# 🚀 Running the Project

## Clone Repository

```bash
git clone https://github.com/yourusername/RailSense-AI.git

cd RailSense-AI
```

---

## Start All Services

```bash
docker-compose up
```

This launches:

```
✓ Agent Hub
✓ Passenger Agent
✓ Operations Agent
✓ Security Agent
✓ Maintenance Agent
```

### Run the Operations Agent locally

```powershell
python -m uvicorn main:app --app-dir M2-operations-agent --reload --port 8001
```

Open the dashboard at `http://localhost:8001/` or the API documentation at
`http://localhost:8001/docs`.

To enable Supabase Phase 4 retrieval, run
`M2-operations-agent/rag/supabase_schema.sql` in the Supabase SQL editor,
configure `SUPABASE_URL` and `SUPABASE_KEY`, and index the corpus:

```powershell
python M2-operations-agent/rag/embed_documents.py
```

---

# 📅 Development Timeline

| Week | Milestone                        |
| ---- | -------------------------------- |
| 1    | Topic selection and architecture |
| 2    | Dataset preparation              |
| 3    | Agent scaffolding                |
| 4    | LLM integration                  |
| 5    | NLP implementation               |
| 6    | Mid Evaluation                   |
| 7    | RAG implementation and grounded Operations predictions |
| 8    | Security hardening               |
| 9    | Full integration                 |
| 10   | Final submission                 |
| 11   | Viva presentation                |

---

# 💼 Commercialization Vision

## Product

**RailSense AI**

AI-powered railway intelligence platform.

## Target Customers

* Railway authorities
* Transport ministries
* Metro operators
* Freight companies

## Business Model

### Starter

Passenger chatbot + basic delay prediction

### Professional

Operations analytics + maintenance intelligence

### Enterprise

Complete AI railway management suite

---

# 👥 Team Roles

| Member   | Role                            |
| -------- | ------------------------------- |
| Member A | Passenger AI Agent              |
| Member B | Operations AI Agent             |
| Member C | Security Agent + Hub            |
| Member D | Maintenance Agent + Integration |

---

# 🌟 Key Innovation

RailSense AI demonstrates:

✅ True multi-agent collaboration
✅ LLM-powered decision support
✅ Secure AI communication
✅ RAG-grounded answers
✅ Explainable predictions
✅ Real-world railway commercialization potential

---

# 📜 License

Academic Project
IT3041 – Information Retrieval & Web Analytics

---

# 🚆 RailSense AI

**Intelligent Railway Operations Powered by Agentic Artificial Intelligence**

```

This version is suitable for a **GitHub repository front page** and looks closer to an industry AI product documentation style rather than an assignment document...........
```
