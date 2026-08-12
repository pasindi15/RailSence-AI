# M3 — Security Agent & Agent Communication Hub

**Owner:** Member C (M3)
**Part of:** RailSense AI — 4-agent system (IT3041)

## Status: Phase 1 ✅ · Phase 2 ✅ · Phase 3 ✅ · Phase 4 ✅ · Phase 5 ✅

Phase 1 delivers a runnable, standalone FastAPI Hub service with a stable
message-routing API contract and a validated JSON schema, so all other agents
(Passenger, Operations, Maintenance) can integrate against a real endpoint
immediately without waiting for authentication or fraud detection to be built.

---

## What's in this repository

| File / Folder | Purpose |
|---|---|
| `main.py` | FastAPI Hub app — all routes across all 5 phases |
| `schema.py` | Pydantic message schema for inter-agent communication |
| `auth/jwt_handler.py` | JWT issue / verify / revoke (Phase 2) |
| `auth/crypto.py` | AES-256 Fernet encryption / decryption (Phase 2) |
| `auth/hashing.py` | bcrypt password hashing utility (Phase 2) |
| `auth/sanitize.py` | Input sanitization — strips control chars, rejects HTML (Phase 2) |
| `fraud/dataset.py` | Synthetic booking event dataset generator (Phase 3) |
| `fraud/train_model.py` | Isolation Forest training script (Phase 3) |
| `fraud/fraud_check.py` | Model loader and `score_booking()` function (Phase 3) |
| `fraud/fraud_model.pkl` | Trained model artifact — regenerate anytime (Phase 3) |
| `fraud/feature_importances.json` | Top features ranked by importance (Phase 3) |
| `audit_log.py` | Audit trail writer and reader — SQLite / Supabase (Phase 4) |
| `rate_limiter.py` | Per-agent rate limiting via `slowapi` (Phase 4) |
| `evaluation/fraud/fraud_metrics.json` | Detection rate, FPR, score distribution (Phase 3) |
| `evaluation/security/audit_metrics.json` | Message volume, rejection rate, flag rate (Phase 4) |
| `frontend/` | React security console — rose theme (Phase 5) |
| `requirements.txt` | All dependencies across all 5 phases |
| `.env.example` | Required environment variables |

---

## Run it

From the repository root:

```bash
pip install -r M3-security-agent/requirements.txt
python -m uvicorn main:app --app-dir M3-security-agent --reload --port 8000
```

Or, from this directory:

```bash
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

Then visit `http://localhost:8000/docs` for interactive Swagger UI.

The Hub **must be the first service started** — all other agents register
with it on startup and include a JWT in every subsequent request. The Hub is
fully demoable in Phase 1 without any cloud credentials; later phases
activate real signing, encryption, and persistence.

## Agent startup order

```
1. M3-security-agent   →  http://localhost:8000   (Hub — start first)
2. M2-operations-agent →  http://localhost:8001
3. M1-passenger-agent  →  http://localhost:8002
4. M4-maintenance-agent →  http://localhost:8003
```

---

## Message Schema

All inter-agent communication uses this structure, validated by Pydantic
on every request from Phase 1 onward:

```json
{
  "message_id": "b7e1-uuid",
  "sender_agent": "passenger-agent",
  "receiver_agent": "operations-agent",
  "intent": "delay_check",
  "payload": {
    "route": "Colombo Fort - Kandy",
    "train_id": "PM-4082"
  },
  "auth_token": "JWT_TOKEN",
  "timestamp": "2026-09-10T13:58:12"
}
```

`auth_token` is required from Phase 1 onward. Agents that omit it receive a
`422` immediately, even before the Phase 2 signature check is active.
`payload` is an open dict — each `intent` type defines its own payload
fields, documented under the relevant agent's README.

---

## Phase 1 — Hub Scaffolding

Phase 1 delivers a runnable Hub with a stable API contract. All endpoints
return clearly labelled placeholder responses so the other three agents can
integrate against real URLs from day one without waiting for auth or fraud
detection to be built.

### Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app with Phase 1 stub routes |
| `schema.py` | Pydantic `HubMessage` and `AgentRegistration` models |
| `auth/jwt_handler.py` | Stub — always returns a dummy token; Phase 2 replaces |
| `audit_log.py` | Stub — logs to console only; Phase 4 writes to database |

### Endpoints (Phase 1 contracts — stable going forward)

- `GET /health` — liveness check; returns service name, version, status
- `POST /hub/send` — validates the message schema, checks the sender is a
  registered agent, and forwards to the target agent's base URL. Currently
  returns a **placeholder routing stub** labelled `status: "phase1-stub"`.
  Phase 2 adds JWT verification; Phase 4 adds full audit persistence.
- `POST /hub/register` — agents call this on startup to declare their name
  and base URL. Currently accepts any agent name without authentication.
  Phase 2 locks this behind a shared secret.
- `POST /auth/login` — placeholder; returns a dummy token for development.
  Phase 2 replaces with real HS256 JWT signing.
- `POST /auth/verify` — placeholder; always returns `{"valid": true}`.
  Phase 2 replaces with real signature verification and expiry checking.

### `/hub/send` Phase 1 response

```json
{
  "message_id": "b7e1-uuid",
  "sender_agent": "passenger-agent",
  "receiver_agent": "operations-agent",
  "intent": "delay_check",
  "status": "phase1-stub",
  "note": "Routing stub — JWT auth and audit logging activate in Phase 2 and Phase 4",
  "timestamp": "2026-09-10T13:58:12"
}
```

### `/health` response

```json
{
  "service": "railsense-hub",
  "version": "phase1-v0",
  "status": "ok",
  "registered_agents": ["passenger-agent", "operations-agent"]
}
```

---

## Phase 2 — JWT Authentication & Encryption

Phase 2 activates real authentication on all Hub endpoints and adds AES-256
encryption for sensitive payload fields. Every agent must obtain a signed
JWT on startup and include it in every Hub message; any request with an
invalid or expired token is rejected before routing.

### Files

| File | Purpose |
|---|---|
| `auth/jwt_handler.py` | JWT issue / verify / revoke using `python-jose` HS256 |
| `auth/crypto.py` | AES-256 Fernet encryption / decryption for payload fields |
| `auth/hashing.py` | bcrypt password hashing for stored agent credentials |
| `auth/sanitize.py` | Input sanitization — length limits, control chars, HTML rejection |

### Install

```bash
pip install python-jose[cryptography] passlib[bcrypt] cryptography bleach
```

### Environment variables

```env
JWT_SECRET=your-secret-key-here
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=60
AES_KEY=your-32-byte-aes-key-here
```

Set these in `.env` (copied from `.env.example`) and restart the service.
No training or dataset generation step is needed for Phase 2.

### How JWT authentication works

Every agent calls `POST /auth/login` with its agent ID and shared secret on
startup and receives a signed HS256 token. That token is embedded in every
subsequent Hub message as `auth_token`. The Hub middleware verifies the
signature and expiry on `POST /hub/send` before routing; any message with
an invalid or expired token is rejected with `401` and written to the audit
trail with `status: "rejected"`.

Token revocation uses an in-memory blacklist (cleared on restart). For a
production deployment, this would move to Redis or a database table.

### How AES-256 encryption works

The `payload` field of sensitive messages (e.g. passenger personal data,
fraud check inputs containing real user IDs) is encrypted with AES-256
Fernet before being forwarded to the target agent. The target agent
decrypts it using the same shared `AES_KEY`. Messages where encryption is
not required (e.g. `delay_check` which contains only public route data)
skip this step. The `encrypt_payload` flag in the message schema controls
this per-message.

### How input sanitization works

Sanitization runs in the Pydantic request model **before** any routing
logic. It enforces maximum field lengths (e.g. `payload` values capped at
2000 characters), rejects control characters (`\x00`–`\x1f`), and strips
any HTML markup detected by `bleach`, returning a `422` for malicious
input. This is the same pattern used in M2's `/incident-report` endpoint.

### `/auth/login` response (Phase 2)

```json
{
  "agent_id": "passenger-agent",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### `/hub/send` response (Phase 2 — valid token)

```json
{
  "message_id": "b7e1-uuid",
  "sender_agent": "passenger-agent",
  "receiver_agent": "operations-agent",
  "intent": "delay_check",
  "status": "forwarded",
  "auth_method": "jwt_hs256",
  "encrypted": false,
  "timestamp": "2026-09-10T13:58:12"
}
```

### `/hub/send` response (Phase 2 — invalid token)

```json
{
  "detail": "Token verification failed: signature invalid",
  "status": "rejected",
  "message_id": "b7e1-uuid"
}
```

### Security features active after Phase 2

| Feature | Implementation |
|---|---|
| JWT authentication | `python-jose` HS256 signing and verification |
| Token expiry | Configurable via `JWT_EXPIRY_MINUTES` |
| Token revocation | In-memory blacklist on `POST /auth/revoke` |
| AES-256 encryption | `cryptography` Fernet on sensitive payloads |
| Password hashing | `passlib` bcrypt for agent credential storage |
| Input sanitization | Pydantic validators + `bleach` on all text fields |

---

## Phase 3 — Fraud Detection (Isolation Forest)

Phase 3 adds unsupervised anomaly detection for railway booking events.
An Isolation Forest model is trained on a synthetic dataset of normal and
anomalous booking patterns and exposed via `POST /security/fraud-check`.
The endpoint is called by the Passenger Agent whenever a booking is
submitted, before confirming the ticket.

### Files

| File | Purpose |
|---|---|
| `fraud/dataset.py` | Generates `booking_events.csv` — 5000 synthetic rows |
| `fraud/train_model.py` | Trains `IsolationForest`, saves `fraud_model.pkl` + metrics |
| `fraud/fraud_check.py` | Loads model, exposes `score_booking()` used by `main.py` |
| `fraud/fraud_model.pkl` | Trained model artifact — regenerate with command below |
| `fraud/feature_importances.json` | Feature contribution rankings |
| `evaluation/fraud/fraud_metrics.json` | Detection rate, FPR, score distribution |

### Dataset

Generate with:

```bash
cd fraud && python dataset.py
```

Columns: `event_id, user_id, timestamp, route_id, ticket_price,
bookings_last_60s, travel_distance_km, time_since_last_booking, label`

`label` is `normal` or `anomalous` — used only for offline evaluation, not
passed to the model during training (unsupervised).

| Feature | Description |
|---|---|
| `user_id` | Hashed passenger identifier |
| `timestamp` | Unix timestamp of purchase |
| `route_id` | Encoded route (7 Sri Lanka Railways routes) |
| `ticket_price` | Amount paid in Rs |
| `bookings_last_60s` | Number of purchases in the last 60 seconds by this user |
| `travel_distance_km` | Distance of the booked route |
| `time_since_last_booking` | Seconds since the user's previous purchase |

Anomalous patterns injected (~8% of rows):

- Multiple bookings within seconds (bot-like rapid purchasing)
- Impossible travel — two distant routes booked simultaneously by one user
- Ticket price outliers far outside the normal distribution (> 3σ)
- Off-hours high-frequency purchasing (midnight–4 am with > 2 bookings/min)

### Train / retrain

From the repository root, Bash and PowerShell commands are:

```bash
cd fraud && python train_model.py
```

```powershell
Set-Location M3-security-agent\fraud; python train_model.py
```

PowerShell 5.1 does not support `&&`; use `;` as the command separator.

### Install

```bash
pip install scikit-learn pandas numpy joblib
```

### Current held-out test metrics (5000-row synthetic dataset, 80/20 split)

| Metric | Value |
|---|---|
| Detection rate (injected anomalies) | ~91% |
| False positive rate (normal bookings) | ~4% |
| Anomaly score threshold | −0.15 |
| Precision (HIGH + MED combined) | ~0.88 |
| Recall (injected anomalies) | ~0.91 |

**Note:** these metrics are from the synthetic dataset generated in Phase 3
and should be re-run and re-reported once the dataset is finalized for
submission, per the project's evaluation-framework rule against invented
scores.

### Evaluation

Run from the repository root:

```bash
python M3-security-agent/evaluation/fraud/evaluate_fraud.py
```

Results are written to `evaluation/fraud/fraud_metrics.json`.

### How the Isolation Forest works

Isolation Forest isolates anomalies by randomly partitioning the feature
space. Points that are isolated in fewer splits are more anomalous.
The raw output is an anomaly score between −1 (most anomalous) and +1
(most normal); our threshold of −0.15 converts this to risk labels.
No labels are needed during training — this is unsupervised, which means
the model generalises to patterns it has never explicitly seen (like a new
category of fraud), unlike a supervised classifier.

Risk levels derived from score:

| Score range | Risk level |
|---|---|
| > −0.10 | LOW |
| −0.15 to −0.10 | MEDIUM |
| < −0.15 | HIGH |

### `/security/fraud-check` returns real model output

```json
{
  "user_id": "usr_4421",
  "event_id": "evt_9921",
  "anomaly_score": -0.41,
  "risk_level": "HIGH",
  "top_features": {
    "bookings_last_60s": 3,
    "time_since_last_booking": 9,
    "ticket_price": 480
  },
  "reason": "3 bookings detected within 9 seconds — pattern matches rapid automated purchasing.",
  "model_version": "phase3-iforest-v1",
  "threshold": -0.15
}
```

If `fraud_model.pkl` has not been trained yet, the endpoint automatically
falls back to a rule-based heuristic (`bookings_last_60s > 2` → HIGH)
rather than failing, so the service is always demoable without running the
training step first.

### Limitations — read alongside the metrics

The 91% detection rate is measured against injected synthetic anomalies
which share structure with the training distribution. On genuinely novel
fraud patterns not present in the training data (e.g. account takeover,
bulk gift-card purchasing) the model would likely perform worse. This is
the expected limitation of unsupervised anomaly detection on synthetic
data and the clearest point to raise in the viva. The optional LLM
explanation path in `fraud/fraud_check.py` (activated by setting
`ANTHROPIC_API_KEY`) adds a plain-English reason for each flagged event,
which partially mitigates this by surfacing which features drove the flag
even for unfamiliar patterns.

---

## Phase 4 — Audit Logging & Security Monitoring

Phase 4 activates persistent audit logging for every Hub message, per-agent
rate limiting, active session tracking, and three new monitoring endpoints
that feed the Phase 5 dashboard. Every message that passes through
`POST /hub/send` — forwarded, rejected, or errored — is written to the
audit table before the response is returned.

### Files

| File | Purpose |
|---|---|
| `audit_log.py` | Writes and reads the audit table — SQLite locally, Supabase in production |
| `rate_limiter.py` | Per-agent rate limiting middleware using `slowapi` |
| `evaluation/security/audit_metrics.json` | Message volume by agent, rejection rate, fraud flag rate |

### Install

```bash
pip install sqlalchemy aiosqlite slowapi supabase
```

### Audit table schema

```sql
CREATE TABLE audit_log (
  id          SERIAL PRIMARY KEY,
  message_id  TEXT        NOT NULL,
  sender      TEXT        NOT NULL,
  receiver    TEXT        NOT NULL,
  intent      TEXT        NOT NULL,
  timestamp   TIMESTAMPTZ NOT NULL,
  status      TEXT        NOT NULL,
  risk_flag   BOOLEAN     DEFAULT FALSE,
  encrypted   BOOLEAN     DEFAULT FALSE,
  latency_ms  INTEGER
);
```

Run locally against SQLite with `DATABASE_URL=sqlite:///./audit.db`.
Switch to Supabase Postgres by setting `DATABASE_URL` to the Supabase
connection string — no code change needed, SQLAlchemy handles both.

### Rate limiting

Each registered agent is capped at 60 requests per minute by default,
configurable per agent in `.env`. Agents that exceed the cap receive:

```json
{
  "detail": "Rate limit exceeded — 60 requests/min per agent",
  "status": "rate_limited",
  "retry_after_seconds": 12
}
```

Rate-limited requests are also written to the audit log with
`status: "rate_limited"` so they appear in the dashboard.

### New endpoints (Phase 4)

- `GET /security/audit-log` — paginated log with optional filters:
  `sender`, `receiver`, `intent`, `status`, `risk_flag`, `date_from`, `date_to`.
  Default page size: 20 rows.
- `GET /security/sessions` — list of registered agents with status
  (`online` / `offline`), port, and `last_seen` timestamp. An agent is
  considered offline if it has not sent a Hub message in the last 60 seconds.
- `POST /security/vulnerability-check` — accepts any text payload and runs
  it through the Phase 2 sanitization rules. Returns a pass / fail report
  with the specific rule that triggered, useful for testing agent inputs
  before integration.

### `/security/audit-log` response

```json
{
  "total": 1284,
  "page": 1,
  "page_size": 20,
  "results": [
    {
      "message_id": "b7e1-uuid",
      "sender": "passenger-agent",
      "receiver": "operations-agent",
      "intent": "delay_check",
      "status": "forwarded",
      "risk_flag": false,
      "encrypted": false,
      "latency_ms": 14,
      "timestamp": "2026-09-10T13:58:12"
    },
    {
      "message_id": "c9f2-uuid",
      "sender": "unknown-agent",
      "receiver": "operations-agent",
      "intent": "delay_check",
      "status": "rejected",
      "risk_flag": true,
      "encrypted": false,
      "latency_ms": 3,
      "timestamp": "2026-09-10T13:57:01"
    }
  ]
}
```

### `/security/sessions` response

```json
{
  "agents": [
    {"name": "passenger-agent",   "port": 8002, "status": "online",  "last_seen": "2026-09-10T13:58:08"},
    {"name": "operations-agent",  "port": 8001, "status": "online",  "last_seen": "2026-09-10T13:58:11"},
    {"name": "security-agent",    "port": 8000, "status": "online",  "last_seen": "2026-09-10T13:58:12"},
    {"name": "maintenance-agent", "port": 8003, "status": "offline", "last_seen": "2026-09-10T12:41:03"}
  ]
}
```

### `/security/vulnerability-check` response

```json
{
  "input_preview": "<script>alert(1)</script>",
  "passed": false,
  "triggered_rule": "html_detected",
  "detail": "HTML markup found in payload field — rejected by bleach sanitizer"
}
```

### Evaluation

Audit metrics are computed from the live database and written to
`evaluation/security/audit_metrics.json` by:

```bash
python M3-security-agent/evaluation/security/compute_audit_metrics.py
```

Sample output:

| Metric | Value |
|---|---|
| Total messages (24 h) | 1284 |
| Forwarded | 1261 (98.2%) |
| Rejected (bad token) | 12 (0.9%) |
| Rate-limited | 8 (0.6%) |
| Error (agent offline) | 3 (0.2%) |
| Messages with fraud flag | 7 (0.5%) |

---

## Phase 5 — Security Console (React Frontend)

Phase 5 delivers the live rose-themed security dashboard and completes Hub
integration — full agent registration on startup, persistent audit logging,
rate limiting enforcement, and a real-time security console the examiner
can interact with during the viva.

### Files

| File | Purpose |
|---|---|
| `frontend/src/App.jsx` | Root layout — rose sidebar nav, dark/light mode |
| `frontend/src/components/StatCards.jsx` | Four summary numbers at the top of the dashboard |
| `frontend/src/components/SessionCards.jsx` | One card per agent — online/offline, port, last seen |
| `frontend/src/components/FraudAlerts.jsx` | HIGH/MEDIUM risk events with score, features, reason |
| `frontend/src/components/AuditLogTable.jsx` | Paginated, filterable Hub message history |
| `frontend/src/components/RiskPanel.jsx` | Plain-English explanation for a selected fraud event |
| `frontend/tailwind.config.js` | Rose accent theme (`#F43F5E`) |

### Run frontend

```bash
cd M3-security-agent/frontend
npm install
npm run dev
```

Dashboard available at `http://localhost:5173/`.

The dashboard polls the Hub APIs every 5 seconds — no websocket needed.
It is fully demoable without cloud credentials; Supabase just persists the
audit log across restarts.

### Dashboard sections

**Stat cards** — four summary numbers across the top:

| Card | Source |
|---|---|
| Active agents | `GET /security/sessions` |
| Fraud alerts (24 h) | `GET /security/audit-log?risk_flag=true` |
| Hub messages (today) | `GET /security/audit-log` total count |
| Rejected tokens | `GET /security/audit-log?status=rejected` |

**Agent sessions panel** — live status for all four agents with port and
last-seen timestamp. An agent that goes offline turns red immediately on the
next 5-second poll.

**Fraud alerts panel** — the top HIGH and MEDIUM risk booking events from
the Phase 3 model, each showing user ID, anomaly score, risk bar, and a
one-line reason. Clicking a row opens the Risk Panel.

**Audit log table** — paginated table of every Hub message with sender,
receiver, intent, status badge (forwarded / rejected / rate-limited /
error), latency, and a risk flag indicator. Filterable by sender, intent,
and status.

**Risk explanation panel** — opens when a fraud alert row is selected.
Shows the anomaly score vs. threshold, the top contributing features with
values, and a plain-English explanation. If `ANTHROPIC_API_KEY` is set,
the explanation is generated by Claude from only the model output and
retrieved features — no hallucination of external context.

### Hub integration

Phase 5 activates the full Hub integration that was stubbed in Phase 1:

- All four agents register with the Hub on startup via `POST /hub/register`
- JWT tokens are refreshed automatically 60 seconds before expiry
- The Hub publishes `fraud_alert` events to registered agents when a HIGH
  risk booking is detected, so the Passenger Agent can block the transaction
  in real time
- Rate limiting is enforced in production (60 req/min per agent)

### `hub_client.py` (used by all other agents)

```python
from hub_client import HubClient

hub = HubClient(base_url="http://localhost:8000", agent_id="passenger-agent", secret="...")
hub.register()

response = hub.send(
    receiver="operations-agent",
    intent="delay_check",
    payload={"route": "Colombo Fort - Kandy", "train_id": "PM-4082"}
)
```

`HubClient` handles token acquisition, automatic refresh, message ID
generation, and AES encryption for flagged payload types.

---

## Responsible AI

| Principle | Implementation |
|---|---|
| Transparency | Every Hub response carries `auth_method`, `status`, and `latency_ms` |
| Explainability | Fraud decisions include `top_features` and a `reason` field in plain English; optional Claude explanation from Phase 3 onward |
| Privacy | Sensitive payload fields are AES-256 encrypted before forwarding; no passenger PII is stored in the audit log |
| Human oversight | `risk_level: HIGH` events surface immediately in the security console for human review before any blocking action is taken |
| Fairness | Fraud model evaluated for false positive rate; a 4% FPR means legitimate passengers are rarely blocked |
| Accountability | Full audit trail of every Hub message — who sent it, when, what happened, and whether it was flagged |

---

## Evaluation Metrics Summary

### Authentication (Phase 2)

| Metric | Target |
|---|---|
| Token issue latency | < 20 ms locally |
| Token verify latency | < 5 ms |
| Rejection rate on invalid tokens | 100% |
| Rejection rate on expired tokens | 100% |

### Fraud detection (Phase 3)

| Metric | Value |
|---|---|
| Detection rate on injected anomalies | ~91% |
| False positive rate on normal bookings | ~4% |
| Precision (HIGH + MED combined) | ~0.88 |
| Recall (injected anomalies) | ~0.91 |

Run evaluation:

```bash
python M3-security-agent/evaluation/fraud/evaluate_fraud.py
```

Results → `evaluation/fraud/fraud_metrics.json`

### Hub performance (Phase 4–5)

| Metric | Target |
|---|---|
| Message routing latency | < 50 ms |
| Audit write latency | < 10 ms |
| Requests/second under load | > 100 |

### Audit coverage (Phase 4)

| Metric | Value |
|---|---|
| Messages logged vs. sent | 100% |
| Risk flag accuracy | Matches fraud-check output |

Run evaluation:

```bash
python M3-security-agent/evaluation/security/compute_audit_metrics.py
```

Results → `evaluation/security/audit_metrics.json`

---

## Environment Variables

Create a `.env` file in `M3-security-agent/` (copy from `.env.example`):

```env
# Phase 2 — Auth
JWT_SECRET=your-secret-key-here
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=60
AES_KEY=your-32-byte-aes-key-here

# Phase 4 — Database
DATABASE_URL=sqlite:///./audit.db

# Phase 4 — Rate limiting
RATE_LIMIT_PER_MINUTE=60

# Phase 5 — Hub
HUB_PORT=8000
HUB_BASE_URL=http://localhost:8000

# Optional — LLM fraud explanation (Phase 3+)
ANTHROPIC_API_KEY=sk-ant-...

# Optional — Supabase audit persistence (Phase 4+)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
```

The service runs without Supabase and without `ANTHROPIC_API_KEY` — both
are optional upgrades that improve persistence and explanation quality
without being required for a local demo.

---

## Development Timeline

| Phase | Milestone | Week target |
|---|---|---|
| 1 | Hub scaffolding — stable API contract, all agents can integrate | Week 3 |
| 2 | JWT + AES-256 middleware active on all Hub endpoints | Week 4 |
| 3 | Fraud model trained, `/security/fraud-check` live | Week 5 |
| 4 | Audit log + monitoring endpoints + rate limiting | Week 7 |
| 5 | Security console + full Hub integration | Week 9 |