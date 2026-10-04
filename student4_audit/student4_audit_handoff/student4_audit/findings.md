# Findings Register — RailSense AI Security & IR Audit (Student 4)

Severity rubric: **Critical** = unauthenticated remote action changing safety/booking state or granting admin on an exposed surface; **High** = auth/authz bypass or PII/credential exposure with minimal preconditions; **Medium** = control weakness needing a precondition or a defence-in-depth gap; **Low** = hardening gap; **Informational** = observation/production gap. Controls that *held* are recorded in RESULTS.md and are not inflated into findings. Risk = impact × likelihood (§ risk matrix). Regenerated in Stage 2 from `results.json`; credentials masked.

## F-01 — Default admin credentials active (M2 admin)
- **Severity: High.** Module(s): M2. Tests: S4-M2-03. Risk: **High** (impact High × likelihood High).
- **Description / root cause:** M2 admin bootstrap falls back to a hard-coded default password for admin@railsense.lk when ADMIN_INITIAL_PASSWORD / ADMIN_PASSWORD are unset. On the tested deployment the default was still valid (one attempt, 200 + admin JWT). Root cause: M2-operations-agent/admin/admin_db.py:444-445; no forced change on first login.
- **Evidence:** evidence/S4-M2-03/default_login_attempts.json
- **Impact:** C/I/A High: full M2 admin scope (officer management, model retrain/rollback, incident approval, audit read). Accountability: actions would be attributed to the legitimate admin identity.
- **Likelihood:** High — High: the value is in source and one request suffices.
- **Severity justification:** High. A CVSS 3.1 base score for an Internet-facing system would be 9.8; rated High here because the console is LAN-only in this deployment and M2 admin has no path to safety state (train flags live in M4 behind separate auth). Would be Critical if Internet-exposed.
- **Mitigation:** *Immediate* — Rotate the admin password on the shared DB; set ADMIN_INITIAL_PASSWORD everywhere. *Long-term* — Remove the literal default (fail closed), one-time random bootstrap secret, forced first-login change, login lockout and alerting. (`M2-operations-agent/admin/admin_db.py:440-450`; e.g. os.environ['ADMIN_INITIAL_PASSWORD'] required at bootstrap + must_change_password flag; effort S; retest: Documented default returns 401; bootstrap without env var refuses to start.)

## F-02 — Hard-coded engineer credentials in M4 source
- **Severity: High.** Module(s): M4. Tests: S4-M4-03. Risk: **High** (impact High × likelihood High).
- **Description / root cause:** M4 engineer accounts are a source-code dict with plaintext, weak passwords compared with ==. The documented admin account logged in (200, token issued); a wrong password returned 401. Root cause: M4-maintenance-agent/main.py:74-79 (_ENGINEER_ACCOUNTS), main.py:846-847 (plaintext comparison).
- **Evidence:** evidence/stage2_supplementary/results.json (G1); evidence/S4-M4-03/flag_revert.json
- **Impact:** Integrity/safety High: the engineer role controls train maintenance flags, which gate ticket sales in M3, and field reports.
- **Likelihood:** High — High: credentials are in the repository and follow a guessable pattern.
- **Severity justification:** High: grants the only safety-relevant write role. Not Critical because the authentication gate itself works (401 without token on all surfaces) and flag changes are visible and reversible.
- **Mitigation:** *Immediate* — Change all four passwords via env/DB; remove them from source. *Long-term* — Move engineers to the DB with bcrypt (reuse M2's officer model), per-user accounts, lockout, MFA for flagging. (`M4-maintenance-agent/main.py:74-79, 840-850`; e.g. bcrypt.checkpw against engineers table; secrets loaded from env; effort M; retest: Source contains no passwords; documented credentials return 401.)

## F-03 — Admin/fraud/cancellation/hub endpoints unauthenticated (public port)
- **Severity: High.** Module(s): M3/Gateway. Tests: S4-M3-02, S4-M3-03. Risk: **High** (impact High × likelihood High).
- **Description / root cause:** Gateway admin and monitor routes proxy to Booking/Hub with no session check. Without a token, on both :3000 (public) and :3001: fraud-reviews (17 cases incl. names, emails, risk scores), cancellations, hub dashboard/timeline; system-health and admin/trains on :3000. Booking /internal/fraud-reviews is also unauthenticated. Root cause: frontend/serve.py:1550, 1665, 1840, 1925, 1982, 2158 (no auth dependency); booking-agent/main.py:705-720.
- **Evidence:** evidence/S4-M3-03/results.json, fraud_queue_unauth.json; evidence/S4-M3-02/results.json; figures/fig_rbac_matrix.png
- **Impact:** Confidentiality High: passenger PII and AI fraud-risk labels disclosed; internal topology (base URLs) disclosed. RAI: exposes who was flagged as a fraud risk by an automated model.
- **Likelihood:** High — High on the LAN: public port bound to 0.0.0.0, plain GET, no auth.
- **Severity justification:** High: unauthenticated read of personal data plus automated risk judgements. Not Critical because the routes are read-only (review actions were not tested and M2's admin API behind the same gateway correctly returns 401).
- **Mitigation:** *Immediate* — Require an officer session on every /api/admin/* and /api/hub/* gateway route; stop serving admin routes on :3000. *Long-term* — Central auth middleware at the gateway plus independent auth in Booking/Security admin routes. (`frontend/serve.py route handlers above; booking-agent/main.py:705-760`; e.g. FastAPI dependency verifying the M2 officer JWT + role claim on an APIRouter prefix; effort M; retest: All listed routes return 401 for none/passenger and 403 for operator where admin-only.)

## F-16 — Cleartext NICs in fraud-case payloads served unauthenticated
- **Severity: High.** Module(s): M3 Booking/Gateway. Tests: S4-M3-03. Risk: **High** (impact High × likelihood High).
- **Description / root cause:** In 4 of 17 fraud cases (8 of 21 passenger objects) booking_details.passengers[] contains a raw 12-digit nic next to nic_masked and nic_hash; last 4 digits match the mask in 8/8. Served unauthenticated via F-03. Corrects the Stage-1 conclusion that NIC masking fully held. Root cause: booking-agent/fraud/review_service.py:99 copies caller payload incl. passengers[].nic into booking_payload; list_cases (review_service.py:40-62) returns it verbatim. Current booking path (booking/service.py:283-291, 379) is sanitised, so the exposure is legacy rows / the helper path.
- **Evidence:** evidence/stage2_supplementary/nic_raw_field_check.json (no values recorded); evidence/S4-M3-03/results.json (nic_cleartext_present true)
- **Impact:** Confidentiality High: national identity numbers are a durable identifier used for identity verification. Data protection: contradicts the README's HMAC/mask claim. Whether values are synthetic could not be determined; treated as PII.
- **Likelihood:** High — High: reachable through the unauthenticated F-03 route.
- **Severity justification:** High on its own (national ID disclosure); combined with F-03 it is the most sensitive exposure found. Not Critical because it affects 4 historical cases, not every booking.
- **Mitigation:** *Immediate* — Scrub nic from stored booking_payload rows (one-off migration); fix F-03. *Long-term* — Strip raw identifiers in create_review_case and apply a response-side allowlist in list_cases; add a regression test that no response contains a raw NIC pattern. (`booking-agent/fraud/review_service.py:95-115, 40-62`; e.g. p.pop('nic', None) before persisting; serializer allowlist {name, nic_masked, nic_hash}; effort S; retest: Scan of fraud-reviews finds 0 raw NIC values; unit test for create_review_case.)

## F-04 — CORS reflects any Origin (+credentials=true)
- **Severity: Medium.** Module(s): M2/M3/M4/Security. Tests: S4-M1-04. Risk: **Medium** (impact Medium × likelihood Medium).
- **Description / root cause:** M2, M4, Security, Booking and Hub use allow_origins=['*'] with allow_credentials=True, so Starlette reflects any Origin with Access-Control-Allow-Credentials: true. M1 returns ACAO * without credentials. Root cause: M2 main.py:100-101; agent-hub/main.py:121-122; booking-agent/main.py:109-110; M4 main.py:254-255; security-agent/main.py:46-47.
- **Evidence:** evidence/static/cors_check.json
- **Impact:** Medium: tokens are Bearer headers from localStorage (not cookies), so credentialed CORS does not currently leak sessions. The permissive origin policy still lets any web page a staff member opens read unauthenticated loopback-only services from their browser, weakening the 127.0.0.1 bind. Becomes High if cookie auth is introduced.
- **Likelihood:** Medium — Medium: requires a victim to visit an attacker page while on the host.
- **Severity justification:** Medium: a real misconfiguration with a cross-origin read path, but session theft is not possible with the current token storage.
- **Mitigation:** *Immediate* — Replace '*' with the two gateway origins; drop allow_credentials where unused. *Long-term* — Shared CORS config module; internal services need no browser CORS at all. (`the five main.py lines above`; e.g. allow_origins=['http://localhost:3000','http://localhost:3001']; effort S; retest: Preflight with Origin https://evil.example returns no ACAO header.)

## F-05 — Internal endpoints lack independent auth (M4 skips JWT)
- **Severity: Medium.** Module(s): M3/M4/Security. Tests: S4-M3-02, S4-M4-03. Risk: **Medium** (impact Medium × likelihood Medium).
- **Description / root cause:** Receivers do not verify the Hub delegation token. Security /internal/fraud-score answered 200 with no token; other internal endpoints reached schema validation (422) with no auth check; M4 /hub/message accepted no-token and wrong-key tokens (200). Root cause: security-agent/main.py:99-105 (no auth dependency); M4 main.py:120-122 (_verify_hub_token returns when JWT_SECRET_KEY unset = fail-open).
- **Evidence:** evidence/S4-M3-02/results.json; evidence/S4-M4-03/results.json (hub_message_signing)
- **Impact:** Integrity Medium: bypasses the Hub's signature, allowlist, rate limit and audit for anyone who can reach a receiver (localhost, gateway pass-through, or SSRF).
- **Likelihood:** Medium — Medium: internal ports are loopback, but the gateway proxies /svc/* on 0.0.0.0.
- **Severity justification:** Medium: a defence-in-depth failure that needs a network precondition; no direct PII or safety write was demonstrated through it.
- **Mitigation:** *Immediate* — Set JWT_SECRET_KEY in M4 and make verification fail closed. *Long-term* — Shared verify_agent_token dependency on every /internal/* and /hub/message route; mTLS or per-agent keys. (`security-agent/main.py:99; M4 main.py:114-133; booking/M2 internal routes`; e.g. Depends(require_hub_token(expected_audience=AGENT_NAME)); effort M; retest: No-token and wrong-key calls to all receivers return 401.)

## F-06 — Public gateways bind 0.0.0.0
- **Severity: Medium.** Module(s): Gateway. Tests: S4-M3-02, S4-M3-03. Risk: **Medium** (impact Medium × likelihood Medium).
- **Description / root cause:** Both gateways listen on 0.0.0.0 (confirmed by netstat); internal agents listen on 127.0.0.1. The gateway re-exposes admin, hub and /svc/* routes to the LAN. Root cause: frontend/serve.py:2454, 2460.
- **Evidence:** evidence/stage2_supplementary/results.json (G5); evidence/S4-M3-02/results.json
- **Impact:** Medium: amplifier that makes F-03, F-05, F-11 reachable from any device on the network.
- **Likelihood:** Medium — Medium: shared campus / Wi-Fi networks.
- **Severity justification:** Medium: no data exposure on its own; it widens who can reach other weaknesses.
- **Mitigation:** *Immediate* — Bind to 127.0.0.1 for local use. *Long-term* — Authenticating reverse proxy/ingress; separate admin plane not exposed to passengers. (`frontend/serve.py:2454, 2460`; e.g. host=os.getenv('GATEWAY_HOST','127.0.0.1'); effort S; retest: netstat shows 127.0.0.1:3000/3001.)

## F-07 — Retrieval below README claims; SI/TA fairness gap; no relevance threshold
- **Severity: Medium.** Module(s): M1/M2/M4. Tests: S4-M1-01, S4-M2-01, S4-M4-01. Risk: **High** (impact Medium × likelihood High).
- **Description / root cause:** Independent retrieval results are below README claims: M1 P@1 0.542 (EN 1.000 / SI 0.375 / TA 0.250), M2 0.875 vs claimed 1.000, M4 0.792 vs claimed 1.000. No retriever applies a relevance threshold (off-topic queries return chunks; M4 FP rate 0.5). Root cause: M1 rag/retriever.py:15-26, 38 (English-only MiniLM, unconditional top_k); M2 evaluation/rag/evaluate_retrieval.py:3-4 (corpus-derived queries); M4 manual_retriever.py:133 (TF-IDF, no cutoff) and shipped eval prefixing gold asset/fault type.
- **Evidence:** evidence/S4-M1-01, S4-M2-01, S4-M4-01 results.json; figures/fig_retrieval_metrics.png, fig_language_gap.png
- **Impact:** Medium: degraded answers for Sinhala/Tamil passengers (fairness); overstated public metrics (transparency); irrelevant 'authoritative' context for off-topic questions.
- **Likelihood:** High — High: affects ordinary usage by every non-English user.
- **Severity justification:** Medium: a quality/fairness defect, not a security breach; LLM declines in S4-M1-02 limited the harm observed. Risk is High because it occurs in normal use every day.
- **Mitigation:** *Immediate* — Publish the independent figures alongside the README numbers. *Long-term* — Multilingual embeddings (e.g. paraphrase-multilingual-MiniLM-L12-v2) or translate-then-retrieve; similarity threshold with an 'I don't know' path; held-out multilingual eval set in CI. (`the three retriever modules and eval scripts`; e.g. if top_distance > tau: return [] (tau tuned on held-out set); effort M; retest: Re-run the 24-query sets: SI/TA P@1 within 0.15 of EN; off-topic FP rate < 0.1.)

## F-12 — One shared HS256 secret for agents and officers
- **Severity: Medium.** Module(s): Platform. Tests: S4-M2-03, S4-M3-01. Risk: **Medium** (impact High × likelihood Low).
- **Description / root cause:** One HS256 JWT_SECRET_KEY signs and verifies both officer/admin tokens and all inter-agent Hub tokens. Root cause: M2 admin/admin_auth.py:22, 154, 161; agent-hub/auth/jwt_utils.py:44-107.
- **Evidence:** Code review; gray-box token minting in scripts/_harness.py demonstrates that the secret suffices for both token types.
- **Impact:** High if leaked: any holder can mint an admin officer token and impersonate any agent; no separation of trust domains.
- **Likelihood:** Low — Low: requires disclosure of the secret (it is in several .env files).
- **Severity justification:** Medium: design weakness with large blast radius but no direct exploit without a prior leak.
- **Mitigation:** *Immediate* — Separate secrets for officer tokens and agent tokens. *Long-term* — RS256/ES256 per-agent key pairs so a compromised agent cannot forge others; key rotation. (`admin_auth.py; jwt_utils.py; .env templates`; e.g. OFFICER_JWT_SECRET vs per-agent private keys with the Hub holding only public keys; effort L; retest: An agent token is rejected by the admin API and vice versa.)

## F-08 — Unverified pending incidents enter Ops Assistant context
- **Severity: Low.** Module(s): M2. Tests: S4-M2-02. Risk: **Low** (impact Low × likelihood Medium).
- **Description / root cause:** Unauthenticated incident reports are held as pending and correctly kept off the public map, but the Operations Assistant's incident tool lists pending items with their raw summary text (labelled _pending_), so attacker-written text enters an LLM-facing tool unsanitised. Re-rated from Medium (Stage 1) to Low. Root cause: M2 ops_agent_tools.py:184-185 (excludes only rejected), summary copied from raw_text; no provenance sanitisation.
- **Evidence:** evidence/S4-M2-02/leak_recheck.json (marker_leaked true), results.json
- **Impact:** Low: officer-facing only, status label shown; potential indirect prompt-injection surface when the Gemini path is live (not exercised in this run).
- **Likelihood:** Medium — Medium: submission is unauthenticated and trivial.
- **Severity justification:** Low: listing the review queue is intended behaviour; the gap is unsanitised untrusted text, and no manipulated answer was observed.
- **Mitigation:** *Immediate* — Quote/escape pending text as data in tool output; never include pending rows in LLM context except in the explicit review view. *Long-term* — Provenance labels and trust tiers on every retrieved item; injection-pattern stripping. (`M2 ops_agent_tools.py:180-200`; e.g. {'trust':'unverified','text':<escaped>} with a system rule that unverified text is not instructions; effort S; retest: Injection marker never appears unquoted in assistant answers.)

## F-09 — No security headers; /docs + /openapi.json open on all services
- **Severity: Low.** Module(s): All. Tests: S4-M1-04, S4-M3-02, S4-M4-03. Risk: **Low** (impact Low × likelihood Medium).
- **Description / root cause:** No X-Content-Type-Options, X-Frame-Options, CSP or HSTS on any service; /docs and /openapi.json return 200 on all 8 services including both gateways. Root cause: FastAPI defaults (docs enabled, no header middleware) in every main.py.
- **Evidence:** evidence/env/recon_summary.json
- **Impact:** Low: clickjacking/MIME-sniffing hardening gap; full API map disclosed.
- **Likelihood:** Medium — Medium.
- **Severity justification:** Low: hardening/information-disclosure, no direct compromise.
- **Mitigation:** *Immediate* — docs_url=None, openapi_url=None in production. *Long-term* — Security-header middleware at the gateway. (`all main.py / serve.py app constructors`; e.g. middleware setting nosniff, DENY, default-src 'self'; effort S; retest: /docs 404; headers present on responses.)

## F-10 — No rate limiting on M1 /chat and M2 /incident-report
- **Severity: Low.** Module(s): M1/M2. Tests: S4-M1-04, S4-M2-02. Risk: **Low** (impact Low × likelihood Medium).
- **Description / root cause:** M1 /chat has no rate limiter (20/20 accepted); M2 /incident-report has no limiter (10/10 near-duplicates accepted). M2/M4 other routes and the Hub do limit. Root cause: No slowapi in M1 backend; M2 main.py:1469 lacks the @limiter decorator present on neighbouring routes.
- **Evidence:** evidence/S4-M1-04/results.json (burst); evidence/S4-M2-02/results.json
- **Impact:** Low: LLM cost amplification and review-queue spam.
- **Likelihood:** Medium — Medium.
- **Severity justification:** Low: availability/cost impact under bounded conditions; contradicts README claim.
- **Mitigation:** *Immediate* — @limiter.limit on both routes. *Long-term* — Gateway-wide per-IP limits; duplicate detection on incident text. (`M1 backend/main.py /chat; M2 main.py:1469`; e.g. @limiter.limit('10/minute'); effort S; retest: Burst of 20 yields 429s.)

## F-11 — Chat history IDOR by session UUID
- **Severity: Low.** Module(s): M1. Tests: S4-M1-03. Risk: **Low** (impact Medium × likelihood Low).
- **Description / root cause:** GET /chat/{session_id}/history returns another session's messages to any caller with the UUID, directly and via the public gateway. Root cause: M1 main.py:1645 (no ownership check); main.py:136-138 validates format only.
- **Evidence:** evidence/S4-M1-03/results.json
- **Impact:** Medium: conversation content (travel details) disclosed if an ID leaks.
- **Likelihood:** Low — Low: UUIDv4 is unguessable; requires leakage.
- **Severity justification:** Low: real IDOR, but only exploitable with a leaked identifier.
- **Mitigation:** *Immediate* — Remove history route from the public pass-through. *Long-term* — Bind sessions to a signed cookie or authenticated principal and check ownership. (`M1 main.py:1645; serve.py:167`; e.g. HMAC-signed session cookie compared to path id; effort M; retest: Reading session A's history from B's context returns 403.)

## F-13 — Unsigned Upstash pub/sub events
- **Severity: Low.** Module(s): M2/M4. Tests: S4-M3-04. Risk: **Low** (impact Medium × likelihood Low).
- **Description / root cause:** delay_alert and maintenance_alert are published to Upstash as plain JSON with no signature; subscribers cannot verify origin. Root cause: M2 hub_client.py:89; M4 hub_client.py:91.
- **Evidence:** Code; evidence/S4-M3-04/results.json
- **Impact:** Medium: forged alerts could mislead consumers.
- **Likelihood:** Low — Low: needs the Upstash token.
- **Severity justification:** Low: design gap behind a credential; not exploited.
- **Mitigation:** *Immediate* — Add an HMAC field with a dedicated key. *Long-term* — Verify signature and schema on consume; reject unsigned. (`both hub_client.py publish functions`; e.g. event['sig']=hmac_sha256(EVENT_KEY, canonical_json); effort S; retest: Unsigned or tampered event is dropped by subscriber.)

## F-14 — No request-body size cap (M1 /chat, Hub /messages)
- **Severity: Low.** Module(s): M1/M3. Tests: S4-M1-04, S4-M3-01. Risk: **Low** (impact Low × likelihood Medium).
- **Description / root cause:** M1 accepted a 120 KB chat message; the Hub forwarded a 200 KB payload. Root cause: M1 main.py:90-92 (message: str, no max_length); Hub payload is a free-form dict.
- **Evidence:** evidence/S4-M1-04/results.json; evidence/S4-M3-01/results.json
- **Impact:** Low: memory and LLM-token cost amplification.
- **Likelihood:** Medium — Medium.
- **Severity justification:** Low: bounded resource impact.
- **Mitigation:** *Immediate* — max_length on message; payload size check in Hub. *Long-term* — Body-size limit at the gateway. (`M1 main.py:90-92; agent-hub message schema`; e.g. Field(..., max_length=2000); reject Content-Length > 64 KB; effort S; retest: 120 KB body returns 413/422.)

## F-15 — M4 assistant answers out-of-role; safety figures not number-guarded
- **Severity: Informational.** Module(s): M4. Tests: S4-M4-02. Risk: **Low** (impact Low × likelihood Medium).
- **Description / root cause:** The M4 engineer assistant answered a passenger-style question with internal asset IDs/health, and emitted numeric limits without a post-generation check against cited manual text (no fabrication was proven). Root cause: No role/scope filter on M4 /chat; number guard not applied to safety figures; invented-ID check skipped when M4 is offline from the shared DB.
- **Evidence:** evidence/S4-M4-02/results.json
- **Impact:** Informational: scope creep; residual over-trust risk for safety figures.
- **Likelihood:** Medium — Medium.
- **Severity justification:** Informational: no incorrect safety value was demonstrated; observed figures were consistent with the manual section returned in S4-M4-04.
- **Mitigation:** *Immediate* — Scope prompt/classifier to engineering questions. *Long-term* — Verify each emitted number appears in a cited chunk; show citations. (`M4 /chat handler and recommendation layer`; e.g. regex numbers in answer ⊆ numbers in retrieved chunks, else fall back to template; effort M; retest: Passenger question is redirected; unsupported number triggers template.)
