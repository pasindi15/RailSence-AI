# RailSense AI — Member C

**Communication Hub** · **Booking & Reservation Agent**

---

## Architecture & Responsibilities

### 1. Communication Hub (`agent-hub/`)
The Central Communication Hub is the mediator for all inter-agent traffic across the RailSense AI platform. It enforces:

```
Receive Structured AgentMessage
      │
      ▼
Validate Schema (Pydantic v2)
      │
      ▼
Verify JWT (PyJWT signature, expiry, sender claim)
      │
      ▼
Check Receiver Agent (Central Registry)
      │
      ▼
Write Audit Trace (audit_logs table)
      │
      ▼
Route via Asynchronous httpx (POST {receiver_url}/internal/messages)
      │
      ▼
Record Route Result (ROUTED or FAILED in audit_logs)
      │
      ▼
Return Destination Response Envelope
```

The Communication Hub **never**:
- calculates ticket fares
- queries seat or train availability
- creates or modifies bookings
- performs NLP classification, RAG retrieval, or LLM inference
- approves or rejects cancellations

### 2. Booking & Reservation Agent (`booking-agent/`)
Processes `booking_request` and `cancel_booking` intents forwarded by the hub. Availability and fare checks are strictly deterministic backend/database operations (Phase 3). Cancellation final approval remains human-in-the-loop.

---

## Folder Structure

```
member-c/
├── COMMUNICATION_CONTRACT.md          ← API contracts and message schemas
├── README.md                          ← Architecture, setup, and Phase 2 guide
│
├── shared/
│   ├── __init__.py
│   └── schemas.py                     ← AgentMessage envelope & MemberCIntent enum
│
├── agent-hub/
│   ├── main.py                        ← FastAPI app (port 8002) with complete Phase 2 pipeline
│   ├── router.py                      ← Asynchronous httpx message router & error mapper
│   ├── validator.py                   ← Receiver agent registry validation
│   ├── registry.py                    ← Logical name → service URL registry
│   ├── hub_database.py                ← SQLAlchemy engine, sessionmaker, & get_db dependency
│   ├── requirements.txt               ← Hub dependencies (FastAPI, PyJWT, httpx, SQLAlchemy)
│   ├── .env.example                   ← Environment variable template
│   ├── auth/
│   │   ├── __init__.py
│   │   └── jwt_utils.py               ← JWT verification, expiry check, & sender validation
│   └── audit/
│       ├── __init__.py
│       └── service.py                 ← Secure audit log persistence (AuditLog table)
│
├── booking-agent/
│   ├── main.py                        ← FastAPI app (port 8003, /internal/messages endpoint)
│   ├── requirements.txt
│   ├── .env.example
│   ├── database/
│   │   ├── __init__.py
│   │   ├── database.py                ← PostgreSQL/SQLite engine & SessionLocal
│   │   └── models.py                  ← ORM models (trains, schedules, bookings, cancellations, audit_logs)
│   └── schemas/
│       ├── __init__.py
│       ├── booking.py                 ← BookingRequest (Pydantic v2)
│       └── cancellation.py            ← CancellationRequest (Pydantic v2)
│
└── tests/
    ├── conftest.py                    ← Global pytest fixtures & default mock transport
    ├── test_phase1.py                 ← Phase 1 verification tests
    ├── test_phase2_validation.py      ← Phase 2 Pydantic & receiver registry validation tests
    ├── test_phase2_jwt.py             ← Phase 2 JWT verification & sender matching tests
    ├── test_phase2_audit.py           ← Phase 2 audit logging & privacy compliance tests
    └── test_phase2_routing.py         ← Phase 2 httpx routing & gateway error handling tests
```

---

## Communication Hub Pipeline Details (Phase 2)

### 1. Schema Validation
Incoming requests to `POST /messages` must match the shared `AgentMessage` schema. Missing fields (`message_id`, `sender_agent`, `receiver_agent`, `intent`, `payload`, `auth_token`, `timestamp`), invalid ISO-8601 timestamps, or unsupported intents fail immediately with **HTTP 422 Unprocessable Entity**.

### 2. JWT Authentication
- Signature and expiry are verified using `PyJWT` with `JWT_SECRET_KEY` and `JWT_ALGORITHM`.
- Supports optional `Bearer ` token prefixes.
- **Sender Claim Matching**: Validates that `decoded["sub"] == message.sender_agent`.
- Invalid signatures, expired tokens, or sender claim mismatches reject the request with **HTTP 401 Unauthorized** and record an audit log with status `REJECTED`.

### 3. Receiver Registry Check
The hub checks `message.receiver_agent` against registered services:
- `passenger-agent` (Port 8001)
- `booking-agent` (Port 8003)
- `security-agent` (Port 8004)
- `operations-agent` (Port 8005)
- `maintenance-agent` (Port 8006)

Unregistered agents (e.g. `random-agent`) are rejected with **HTTP 404 Not Found** and recorded as `REJECTED` in the audit log without exposing internal host addresses.

### 4. Audit Logging & Privacy
- Initial message receipt is recorded in the `audit_logs` table (`status: AUTHENTICATED`).
- **Privacy Enforcement**:
  - `auth_token` and JWT secret keys are **NEVER** stored in the database.
  - Message `payload` contents are not stored in audit logs.
- Audit fields stored: `message_id`, `sender_agent`, `receiver_agent`, `intent`, `status`, `timestamp`, `error_message`.
- Status lifecycle: `REJECTED`, `AUTHENTICATED`, `ROUTED`, `FAILED`.

### 5. Asynchronous HTTP Routing (`httpx`)
The hub resolves the target endpoint as `{receiver_base_url}/internal/messages` and forwards the structured `AgentMessage` using `httpx.AsyncClient`.
- Configurable timeout via `HTTP_TIMEOUT` (default: 5.0 seconds).
- Downstream errors are mapped to clean HTTP status codes without leaking internal stack traces:

| Downstream Condition | Hub HTTP Code | Hub Error Message | Audit Status |
|---|---|---|---|
| Unregistered receiver | `404 Not Found` | `"Receiver agent '<agent>' is not registered..."` | `REJECTED` |
| Connection refused / network error | `503 Service Unavailable` | `"Destination agent '<agent>' is unavailable (connection refused)."` | `FAILED` |
| Downstream timeout | `504 Gateway Timeout` | `"Destination agent '<agent>' timed out."` | `FAILED` |
| Destination 5xx server error | `502 Bad Gateway` | `"Destination agent '<agent>' returned a server error (HTTP <status>)."` | `FAILED` |
| Destination 4xx client error | `502 Bad Gateway` | `"Destination agent '<agent>' returned an error (HTTP <status>)."` | `FAILED` |
| Destination 2xx / 202 Success | `200 OK` | Structured response envelope | `ROUTED` |

---

## Environment Variables

### Agent Hub (`agent-hub/.env`)

| Variable | Default / Example | Purpose |
|---|---|---|
| `APP_HOST` | `0.0.0.0` | Binding host |
| `APP_PORT` | `8002` | Hub port |
| `JWT_SECRET_KEY` | `change-me` | Secret key for JWT verification |
| `JWT_ALGORITHM` | `HS256` | Algorithm for JWT verification |
| `PASSENGER_AGENT_URL` | `http://localhost:8001` | Passenger Agent URL |
| `BOOKING_AGENT_URL` | `http://localhost:8003` | Booking Agent URL |
| `SECURITY_AGENT_URL` | `http://localhost:8004` | Security Agent URL |
| `OPERATIONS_AGENT_URL`| `http://localhost:8005` | Operations Agent URL |
| `MAINTENANCE_AGENT_URL`| `http://localhost:8006`| Maintenance Agent URL |
| `DATABASE_URL` | `postgresql://...` or `sqlite:///...` | Audit logging database connection |
| `HTTP_TIMEOUT` | `5.0` | Downstream request timeout in seconds |
| `LOG_LEVEL` | `info` | Logging verbosity |

---

## Local Run & Test Commands

```bash
# 1. Start the Agent Hub (port 8002)
cd member-c/agent-hub
uvicorn main:app --host 0.0.0.0 --port 8002 --reload

# 2. Start the Booking Agent (port 8003)
cd member-c/booking-agent
uvicorn main:app --host 0.0.0.0 --port 8003 --reload

# 3. Run all Phase 1 and Phase 2 test suites
cd member-c
pytest tests/ -v
```

---

## What Phase 2 Implements
- [x] Pydantic v2 `AgentMessage` validation on `POST /messages`
- [x] Inter-agent JWT authentication and sender claim verification
- [x] Receiver agent registry check against known services
- [x] Traceable, privacy-preserving audit logging to `audit_logs` table
- [x] Asynchronous `httpx` message routing to `{receiver}/internal/messages`
- [x] Gateway error mapping (502, 503, 504) without stack trace leakage
- [x] Comprehensive automated test coverage (75 passed tests)

---

## What is Intentionally NOT Implemented in Phase 2
The following features are strictly reserved for Phase 3 and later phases:
- **Booking availability & schedule querying** (Phase 3)
- **Deterministic fare calculation** (Phase 3)
- **Booking creation database writes** (Phase 3)
- **Cancellation eligibility & penalty calculation** (Phase 3)
- **NLP reason categorization & AI sentiment analysis** (Phase 4)
- **RAG policy retrieval & LLM explanations** (Phase 4)
- **Admin approval/rejection workflows** (Phase 5)
- **Email/SMS notification dispatch** (Phase 5)
