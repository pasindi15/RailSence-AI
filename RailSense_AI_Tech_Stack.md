# RailSense AI — Proposed Technology Stack

**Project:** IT3041 — Information Retrieval & Web Analytics
**Domain:** Railway — Multi-Agent System
**Architecture:** 4 cooperating agents + centralized Agent Communication Hub

---

## 1. Overview

RailSense AI is deployed as a set of independently containerized FastAPI services (Passenger, Operations, Security, Maintenance, and the Hub), backed entirely by managed cloud data services, with a Next.js frontend. This design was chosen specifically so the system can be cloned from GitHub and run identically on **any PC** with Docker installed — no local database setup, no state to sync between machines, and no "works on my machine" issues during demos or the viva.

---

## 2. Backend — All 4 Agents + Hub

| Component | Technology |
|---|---|
| API framework | FastAPI (Python 3.11) |
| Data validation | Pydantic v2 |
| ASGI server | Uvicorn |
| Inter-agent HTTP calls | httpx (async client) |
| Authentication | PyJWT + passlib[bcrypt] |
| Encryption (PII at rest) | cryptography (Fernet / AES) |
| Rate limiting | slowapi |
| Input sanitization | Pydantic constrained types + bleach |

---

## 3. Data Layer — Cloud-Hosted

All persistent data lives in managed cloud services rather than self-hosted containers. This keeps the local Docker Compose setup lightweight (only the 5 Python services) and ensures every teammate — and the lecturer, on any machine — sees the exact same live data.

| Data | Service | Notes |
|---|---|---|
| Relational DB (users, tickets, transactions, audit log, maintenance records) | Supabase (Postgres) | Free tier, instantly hosted |
| Vector store / RAG (FAQs, incidents, fraud cases, manuals) | Supabase pgvector | Same Postgres instance — one less service to manage |
| Pub/sub events (`delay_alert`, `maintenance_alert`) | Upstash Redis | Serverless, REST-based, free tier |
| File storage (manuals, uploaded files) | Supabase Storage | Only needed if storing raw PDFs |

---

## 4. LLM & NLP

| Component | Technology |
|---|---|
| LLM (response composition, explanations, recommendations) | Claude API or OpenAI API (single provider, shared key) |
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`) — local, no API cost |
| NER | spaCy |
| Language detection (Sinhala / Tamil / English) | fasttext `lid.176` or langdetect |
| Summarization & classification | LLM prompts (simpler than standing up a separate HF pipeline) |

---

## 5. Machine Learning

| Task | Technology |
|---|---|
| Delay prediction | scikit-learn (RandomForestRegressor / GradientBoostingRegressor) |
| Fraud / anomaly detection | scikit-learn (IsolationForest) |
| Maintenance health prediction | scikit-learn regression or threshold-based logic |
| Model persistence | joblib / pickle |

---

## 6. Frontend

| Layer | Technology |
|---|---|
| Framework | Next.js (React) |
| Styling | Tailwind CSS |
| Data fetching | TanStack Query (React Query) |
| Charts | Recharts |
| Icons | lucide-react |

---

## 7. Deployment & Version Control

| Component | Technology |
|---|---|
| Containerization | Docker + Docker Compose |
| Version control | GitHub |
| Backend cloud deploy (optional, live URL) | Render or Railway |
| Frontend cloud deploy | Vercel |
| Local / multi-PC demo | `docker-compose up` — no cloud deployment required |

---

## 8. Why This Stack Supports Multi-PC Demos

Because the data layer (Postgres, vector store, Redis, file storage) is entirely cloud-hosted, `docker-compose.yml` only needs to bring up the five stateless Python services:

```yaml
services:
  hub
  passenger-agent
  operations-agent
  security-agent
  maintenance-agent
```

No database containers, no local volumes, no state to lose or re-seed between machines.

**Practical benefits:**

1. **Any PC with Docker + internet can run the full system identically.** Clone the repo, run `docker-compose up`, done.
2. **All agents on any PC share the same live data.** A demo on one laptop and a demo on a lab PC the next day use the exact same database, embeddings, and fraud cases — nothing needs to be re-seeded.
3. **The frontend can run locally or already be live on Vercel**, so a lecturer can open a URL directly without any local setup at all.

---

## 9. Environment Configuration

```
.env.example      → committed to GitHub (placeholder values only)
.env               → gitignored; shared securely among team members
docker-compose.yml → committed; spins up only the 5 Python services
```

**Required environment variables (`.env.example`):**

```
DATABASE_URL=postgresql://...supabase.co/...
SUPABASE_URL=...
SUPABASE_KEY=...
UPSTASH_REDIS_URL=...
UPSTASH_REDIS_TOKEN=...
ANTHROPIC_API_KEY=...      # or OPENAI_API_KEY
JWT_SECRET=...
```

All four team members point their local Docker setup at the same Supabase and Upstash project using this shared `.env` file.

---

## 10. Demo-Day Strategy

The system is set up to be demoable in two ways simultaneously:

- **Local run (safety net):** `docker-compose up` on any PC with Docker and the shared `.env` file — works even without internet access to a deployed frontend.
- **Live deployment:** Backend on Render/Railway, frontend on Vercel, for a permanent live URL that can be opened instantly on any machine with no setup at all.

This dual approach ensures the system can be demonstrated reliably regardless of which PC or environment the lecturer requests.
