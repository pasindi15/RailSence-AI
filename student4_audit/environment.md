# Evaluation Environment & Methodology — Student 4 (Information Retrieval & Security Assessment)

## System under test
- **Project:** RailSense AI (multi-agent Sri Lanka Railways platform), this repository.
- **Commit:** `8b66312` (branch `main`).
- **Scope:** local instance only, authorised by the repository owner. All four modules (M1–M4).
- **Assessment date:** 2026-09-28 (Asia/Colombo).

## Host / platform
| Item | Value |
| --- | --- |
| OS | Windows 11 Home 10.0.26200 |
| Python | 3.13.2 |
| Node.js | v24.2.0 |
| Shell | PowerShell + Git Bash |
| HTTP libs | httpx 0.28.1, requests 2.34.2 |
| JWT lib | PyJWT 2.10.1 |

## Services (all confirmed healthy at test time)
| Service | Port | Bind | Health |
| --- | --- | --- | --- |
| Gateway (user) | 3000 | **0.0.0.0** (LAN-reachable) | up |
| Gateway (admin) | 3001 | **0.0.0.0** (LAN-reachable) | up |
| M1 Passenger | 8001 | 127.0.0.1 | 200 |
| M3 Hub | 8002 | 127.0.0.1 | 200 |
| M3 Booking | 8003 | 127.0.0.1 | 200 |
| Security/Fraud | 8004 | 127.0.0.1 | 200 |
| M2 Operations | 8005 | 127.0.0.1 | 200 |
| M4 Maintenance | 8006 | 127.0.0.1 | 200 |

Bind addresses from OS socket listing (`netstat`) and `frontend/serve.py:2454/2460`.

## LLM / optional features — live vs fallback (affects what each test proves)
Loaded from `.env` (root) + `M4-maintenance-agent/.env`. **Key values never read into output; presence only.**
| Key | Present | Effect at test time |
| --- | --- | --- |
| `GEMINI_API_KEY` | yes | M2 Operations Assistant — **however runtime showed `rule_based_fallback`** for all probes (Gemini path not exercised live; see S4-M2-04) |
| `OPENROUTER_API_KEY` | yes | M1 chat replies **LLM-live** (confirmed real LLM phrasing) |
| `GROQ_API_KEY` | yes (M4 .env) | M4 engineer assistant **LLM-live** (Groq) |
| `UPSTASH_REDIS_URL/TOKEN` | yes (M4 .env) | pub/sub configured |
| `SUPABASE_URL/SECRET_KEY/DATABASE_URL` | yes | shared DB live; M2 incident retrieval uses **pgvector**; M4 has **no Supabase** → manual retrieval uses **local TF-IDF** |
| `NIC_HMAC_SECRET`, `JWT_SECRET_KEY` | yes | HMAC + JWT active |

## Identities / tokens used
- **none** — no token.
- **passenger** — M1 chat session (no login; UUID session id).
- **operator** — `operations_engineer` officer. Built two ways: (a) real login of an `S4TEST_` officer created via the admin API (later deactivated); (b) gray-box minted token signed with `JWT_SECRET_KEY` (random `sub` not in DB) — used for RBAC probing to avoid DB writes.
- **admin** — real login as the documented default admin `admin@railsense.lk` (see F-01).
- **agent tokens** (Hub) — gray-box, signed with the shared `JWT_SECRET_KEY` per `agent-hub/auth/jwt_utils.py` semantics.

## Tooling (reproducible; all scripts under `scripts/`)
`recon_endpoints.py` (OpenAPI/health capture), `_harness.py` (tokens, secret loading, evidence scrubbing), and one script per test (`test_m1_*`, `test_m2_*`, `test_m3_*`, `test_m4_*`). All traffic is to `127.0.0.1`/localhost only.

## Ground rules honoured
- **Assess, don't fix** — no source file edited (only local runtime data/log stores changed as a documented byproduct of authorised write-tests; see RESULTS.md §"S4TEST data & cleanup").
- **No fabrication** — every "Actual Behaviour" is from a captured request/response under `evidence/`.
- **Secrets masked** — output scrubbed for `eyJ…`, `sk-…`, `gsk_…`, `AIza…`; JWTs truncated to 12 chars.
- **Bounded load** — bursts ≤ 50, login attempts ≤ 5 (documented defaults only).
- **Cleanup** — all `S4TEST_` records reverted/deleted/deactivated/resolved (see RESULTS.md).

## One accidental side effect (disclosed)
An M2 admin `POST /admin/api/model/retrain` (RBAC test) executed synchronously and retrained the delay model. Impact was cosmetic (metrics byte-identical; only `trained_at` + a new archived version). Reverted per owner decision (`git checkout` of the two files + deletion of the new version artifacts). No mutating admin endpoint was completed as an authorised user thereafter.
