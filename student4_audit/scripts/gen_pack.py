# -*- coding: utf-8 -*-
"""Generate REPORT_INPUT_PACK.md, RESULTS.md and findings.md from results.json + field files.
Single source of truth = results.json (built by build_stage2.py)."""
import json, pathlib
A = pathlib.Path(__file__).resolve().parents[1]
D = json.loads((A / "results.json").read_text(encoding="utf-8"))
TF = json.loads((A / "scripts/_stage2_test_fields.json").read_text(encoding="utf-8"))
FF = json.loads((A / "scripts/_stage2_finding_fields.json").read_text(encoding="utf-8"))
tests = D["tests"]; findings = D["findings"]; meta = D["meta"]
sev_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Informational": 4}
findings = sorted(findings, key=lambda f: (sev_order[f["severity"]], f["id"]))
def fget(fid): return next(f for f in findings if f["id"] == fid)
out = []
W = out.append

# ============================= REPORT_INPUT_PACK.md =============================
W("# RailSense AI — AI Vulnerability Assessment: Report Input Pack")
W("### Student 4 · Information Retrieval & Security Assessment")
W("")
W("> Self-contained hand-off for the report writer. Every number, status code and quote below traces to "
  "`student4_audit/evidence/**` (full logs) — paths are given per item. Secrets are masked. Figures are in "
  "`student4_audit/figures/`. This pack maps 1:1 to the required report sections (A→executive summary … "
  "I→reflection). Placeholders `[ASK USER]` must be filled by the student.")
W("")

W("## A. Metadata")
W("")
W("| Field | Value |")
W("| --- | --- |")
W(f"| Student name | [ASK USER] |")
W(f"| Index / registration no. | [ASK USER] |")
W(f"| Group ID | [ASK USER] |")
W(f"| Assigned specialisation | Student 4 — Information Retrieval & Security Assessment |")
W(f"| Lecturer / module | [ASK USER] · IT3041 Information Retrieval and Web Analytics |")
W(f"| System under test | RailSense AI (multi-agent Sri Lanka Railways platform) |")
W(f"| Git commit tested | `{meta['commit']}` (branch `{meta['branch']}`) |")
W(f"| Testing window | {meta['testing_window']} (Asia/Colombo) |")
W(f"| Suggested report title | *Adversarial Assessment of Retrieval Integrity and Access Control in a Multi-Agent Railway Assistant (RailSense AI)* |")
W("")

o = meta["outcomes"]; s = meta["findings_by_severity"]
W("## B. Executive-summary inputs")
W("")
W("**Objective (2 sentences).** This assessment independently evaluated RailSense AI's information-retrieval "
  "quality and security posture across all four agents (M1–M4), covering retrieval accuracy, retrieval "
  "manipulation, hallucination, source reliability, authentication, authorization, API security and "
  "communication-protocol security. It combined black-box probing of unauthenticated surfaces, gray-box "
  "testing with minted role tokens, and white-box code review to establish root cause for each result.")
W("")
W(f"- **Tests:** 16 (≥ 15 required). **Outcomes:** PASS {o['PASS']} · PARTIAL {o['PARTIAL']} · FAIL {o['FAIL']} · NOT EXECUTED {o['NOT EXECUTED']}.")
W(f"- **Findings:** {len(findings)} — Critical {s['Critical']} · High {s['High']} · Medium {s['Medium']} · Low {s['Low']} · Informational {s['Informational']}.")
W("")
W("**Top 5 findings (one-line impact):**")
for fid in ["F-03", "F-16", "F-01", "F-02", "F-07"]:
    f = fget(fid); W(f"- **{f['id']} ({f['severity']}) — {f['title']}:** {fget(fid)['impact_description'].split(':',1)[-1].strip().split('.')[0]}.")
W("")
W("**Three strongest controls observed (things that held):**")
W("- **Inter-agent protocol auth (Hub).** 10/10 forged/expired/spoofed AgentMessages rejected and replay "
  "de-duplicated at runtime — `verify_agent_token` pins algorithms and checks audience + sender binding (S4-M3-01).")
W("- **M2 admin RBAC + JWT.** Every admin route enforced 401/403/200 by identity and all 6 token forgeries "
  "(alg:none, re-sign, wrong-key, expired, query-string, missing) returned 401 (S4-M2-03).")
W("- **Input validation & append-only audit.** HTML/oversized incident text rejected (422); telemetry fuzz "
  "produced no 500s; the Hub audit log records rejected events and exposes no secrets (S4-M2-02, S4-M4-03, S4-M3-04).")
W("")
W("**Overall security-posture assessment (one sentence, evidence-based).** RailSense AI implements strong "
  "*per-component* controls (protocol signing, RBAC, NIC hashing, input validation, rate-limited audit) but "
  "has a weak *perimeter and defence-in-depth*: the public gateway (bound 0.0.0.0) serves admin, fraud and "
  "hub-monitor data — including cleartext NICs — without authentication, internal receivers do not re-verify "
  "the Hub token, and default/hard-coded credentials remain active, so the four High-risk findings are all "
  "access-control or credential failures rather than cryptographic ones.")
W("")

W("## C. Scope of testing")
W("")
W("**System evaluated.** RailSense AI is a multi-agent assistant for Sri Lanka Railways. A browser front end "
  "reaches four FastAPI agents through two gateways: M1 Passenger (FAQ chat), M2 Operations (delay analytics, "
  "incident management, admin console), M3 (Agent Hub + Booking + Security/fraud), and M4 Maintenance (asset "
  "health, engineer assistant). Agents communicate over a signed Hub protocol and an Upstash pub/sub channel; "
  "shared state is in Supabase (Postgres + pgvector). LLMs are OpenRouter (M1), Gemini (M2), Groq (M4).")
W("")
W("**Component table.**")
W("")
W("| Module | Role | Framework / LLM / retrieval | Port (bind) | Mode active during testing | In scope? |")
W("| --- | --- | --- | --- | --- | --- |")
W("| Gateway (user) | Public reverse proxy | FastAPI (`frontend/serve.py`) | 3000 (**0.0.0.0**) | pass-through live | yes |")
W("| Gateway (admin) | Admin reverse proxy | FastAPI | 3001 (**0.0.0.0**) | pass-through live | yes |")
W("| M1 Passenger | FAQ chat | FastAPI · OpenRouter **live** · ChromaDB MiniLM (22 chunks / 3 docs) | 8001 (127.0.0.1) | LLM live, English embeddings | yes |")
W("| M2 Operations | Delay analytics, incidents, admin | FastAPI · Gemini (**fallback**) · **pgvector** incidents | 8005 (127.0.0.1) | assistant in `rule_based_fallback` | yes |")
W("| M3 Agent Hub | Inter-agent broker | FastAPI · JWT · SQLite/PG audit | 8002 (127.0.0.1) | live | yes |")
W("| M3 Booking | Bookings, fraud queue | FastAPI · Supabase | 8003 (127.0.0.1) | live | yes |")
W("| M3 Security | Fraud scoring | FastAPI · local model | 8004 (127.0.0.1) | live | yes |")
W("| M4 Maintenance | Asset health, engineer chat | FastAPI · Groq **live** · **local TF-IDF** (79 sections / 8 manuals) | 8006 (127.0.0.1) | LLM live, no Supabase | yes |")
W("| Supabase | Shared DB + pgvector | managed Postgres | — | live (data store) | partial (not attacked) |")
W("| Upstash Redis | pub/sub | managed Redis | — | configured | partial (code review only) |")
W("| LLM providers | OpenRouter/Gemini/Groq | external SaaS | — | keys present | no (not attacked) |")
W("")
W("**Corpus / dataset sizes actually present (verified this session).**")
W("")
W("| Item | Size | Source |")
W("| --- | --- | --- |")
W("| M1 FAQ chunks (ChromaDB `passenger_faq`) | 22 embeddings from 3 docs (fares/policies/schedules) | `.chroma/chroma.sqlite3` |")
W("| M2 incident corpus | 7 seed incident notes across 5 types; indexed as pgvectors | `data/incident_reports.jsonl` |")
W("| M2 operations history | 3,900 trip records | `/health` `history_records`, `operations_history.csv` |")
W("| M2 officers / roles | 8 officers (roles: admin, operations_engineer) | `data/officers.json` |")
W("| M4 manual sections (TF-IDF) | 79 sections from 8 `.txt` manuals | `manuals/*.txt` |")
W("| M4 asset history | 1,440 asset rows | `data/assets_history.csv`, `/api/dashboard` |")
W("| Fraud review cases | 17 (8 passenger objects carry raw NIC) | `/api/admin/fraud-reviews` |")
W("| Retrieval test sets (built by S4) | 24 + 6 (M1), 24 + 4 (M2), 24 + 6 (M4) | `scripts/test_m*_01_retrieval.py` |")
W("")
W("**Endpoint inventory summary** (from `endpoint_inventory.md`, 147 endpoints across 8 services):")
W("")
W("| Auth class | Count | Notes |")
W("| --- | :-: | --- |")
W("| No auth (public/none) | 70 | includes intended-public reads and the exposed admin/hub routes |")
W("| Auth verified enforced | 45 | M2 admin (require_admin), Hub agent JWT, M4 engineer-token |")
W("| **FINDING — missing/weak auth** | 32 | admin/fraud/hub via gateway, internal receivers, M4 /hub/message |")
W("")
W("Security-relevant endpoints (compact):")
W("")
W("| Endpoint | Intended | Observed | Test |")
W("| --- | --- | --- | --- |")
W("| `POST :8005/admin/api/login` | credentialed | default admin password works | S4-M2-03 (F-01) |")
W("| `GET :3000/api/admin/fraud-reviews` | admin | 200 unauth, PII + raw NIC | S4-M3-03 (F-03, F-16) |")
W("| `GET :3000/api/hub/timeline` `dashboard` | admin | 200 unauth | S4-M3-03 (F-03) |")
W("| `POST :8004/internal/fraud-score` | Hub-signed | 200 no token | S4-M3-02 (F-05) |")
W("| `POST :8006/hub/message` | Hub-signed | accepts no-token/forged | S4-M4-03 (F-05) |")
W("| `POST :8006/api/engineer-login` | credentialed | hard-coded password works | S4-M4-03 (F-02) |")
W("| `POST :8006/api/flag-train` | engineer-token | 401 on all surfaces (held) | S4-M4-03 |")
W("| `POST :8002/messages` | agent JWT | forgeries 401 (held) | S4-M3-01 |")
W("| `GET :8001/chat/{id}/history` | owner | 200 no token (IDOR) | S4-M1-03 (F-11) |")
W("")
W("**Scope limitations (concrete).**")
W("- Local single-instance only, on 127.0.0.1 / gateway 0.0.0.0; authorised by the repository owner.")
W("- Synthetic `S4TEST_` data for all writes; reverted in the same script (see K/cleanup).")
W("- **Shared Supabase caution:** write-tests confined to `S4TEST_` rows; no bulk or destructive DB ops.")
W("- External SaaS (Supabase, Upstash, OpenRouter, Gemini, Groq) **not attacked**; only the RailSense "
  "services in front of them.")
W("- Bounded load only: bursts ≤ 50, ≤ 5 default-credential attempts, no DoS.")
W("- Admin **write** actions (retrain/rollback, incident approve/reject, officer edits, flag-train, Hub "
  "event control) tested at **auth-gate level**; only `S4TEST_` data mutations were completed and reverted.")
W("- M2 assistant ran in **rule-based fallback** (Gemini not exercised); LLM-path number-guard unverified.")
W("- No TLS/network-layer testing beyond bind-address enumeration.")
W("- Prompt-injection depth, privacy law and broader Responsible-AI analysis are left to other "
  "specialisations; this pack covers the RAI angles that its own tests evidence (§K).")
W("- Retrieval ground-truth sets are moderate (24–30 queries): indicative, not census-grade.")
W("")

W("## D. Evaluation methodology")
W("")
W("**Approach.** Gray-box overall: black-box for unauthenticated probes (no token), gray-box for RBAC "
  "(validly-signed role tokens minted from the shared secret, using a random `sub` not in the DB to avoid "
  "touching real officers), and white-box code review to establish root cause (file:line) for every result.")
W("")
W("**Process actually followed.** (1) Recon — capture `/openapi.json` + `/health` on all 8 services "
  "(`recon_endpoints.py`). (2) Endpoint inventory + auth intent (`endpoint_inventory.md`). (3) Baseline — "
  "confirm modes (LLM live vs fallback, pgvector vs TF-IDF). (4) Per-area tests (one script per test). (5) "
  "Evidence capture with a secret-scrubbing harness. (6) Triage into the findings register with severity + "
  "root cause. (7) Stage-2 self-audit: re-run under-evidenced probes, correct the NIC conclusion, generate figures.")
W("")
W("**Test-selection rationale.** 4 tests per module × 4 modules = 16, arranged so each of the 8 Student-4 "
  "areas is covered ≥ 2× (coverage matrix below / `figures/fig_coverage_matrix.png`). Within a module the "
  "four tests split into retrieval-quality, hallucination/source, and two security tests (authn/authz and "
  "API/protocol), matching the module's dominant risk.")
W("")
W("**Coverage matrix (16 × 8).**")
W("")
areas8 = ["Retr. Acc.", "Retr. Manip.", "Halluc.", "Source Rel.", "AuthN", "AuthZ", "API Sec.", "Comm-Proto."]
amap = ["Retrieval Accuracy", "Retrieval Manipulation", "Hallucination due to Retrieval", "Source Reliability",
        "Authentication", "Authorization", "API Security", "Communication Protocol Security"]
W("| Test | " + " | ".join(areas8) + " |")
W("| --- " + "| :-: " * 8 + "|")
for t in tests:
    row = "".join(" ✔ |" if amap[i] in t["areas"] else " |" for i in range(8))
    W(f"| {t['id']} |" + row)
W("| **Total** | " + " | ".join(str(sum(1 for t in tests if amap[i] in t["areas"])) for i in range(8)) + " |")
W("")
W("**Tools used.**")
W("")
W("| Tool / library | Version | Purpose |")
W("| --- | --- | --- |")
W("| Python | 3.13.2 | test harness runtime |")
W("| httpx | 0.28.1 | HTTP client for all probes |")
W("| requests | 2.34.2 | ancillary requests |")
W("| PyJWT | 2.10.1 | mint/forge JWT tokens (alg:none, wrong-key, expired, tamper) |")
W("| matplotlib | 3.10.9 / PIL 10.4.0 | figures |")
W("| ripgrep / git | — | white-box code review, root-cause file:line |")
W("| `scripts/recon_endpoints.py` | — | capture OpenAPI + health |")
W("| `scripts/_harness.py` | — | role tokens, secret loading (never printed), evidence scrubbing |")
W("| `scripts/test_m{1..4}_*.py` | — | one script per test |")
W("| `scripts/supp_stage2.py` | — | Stage-2 gap-closure probes (G1–G6) |")
W("| `scripts/build_stage2.py`, `gen_pack.py` | — | results.json, figures, this pack |")
W("")
W("**Testing environment.** " + f"{D['environment']['os']}, Python {D['environment']['python']}, Node "
  f"{D['environment']['node']}, PowerShell + Git Bash. Services launched via the project's `start.py`; all 8 "
  "confirmed healthy. Internal agents bind 127.0.0.1; both gateways bind 0.0.0.0. Active modes: M1 OpenRouter "
  "live, M4 Groq live, M2 assistant rule-based fallback; M2 incident retrieval pgvector, M4 manual retrieval "
  "local TF-IDF.")
W("")
W("**Evaluation criteria (pass/fail definitions).**")
W("- *Retrieval accuracy* — pass if independent (out-of-corpus) P@1 is within ~0.15 of the README claim and "
  "no large per-language gap; measured with P@1/P@3/(P@5)/MRR against a labelled set, random baseline stated.")
W("- *Hallucination* — fail if the assistant emits a fact/number/ID absent from retrieved context or confirms "
  "a false premise; pass if it declines or grounds and attributes sources.")
W("- *Retrieval manipulation* — fail if attacker-controlled text changes an answer or reaches an LLM context "
  "unsanitised; pass if untrusted content is quarantined.")
W("- *Source reliability* — pass if provenance is labelled and unverified content is excluded/marked.")
W("- *Authentication* — fail if a forged/expired/absent credential is accepted, or a default/hard-coded "
  "credential works.")
W("- *Authorization* — fail if an identity reaches data/actions above its role (IDOR or missing role check).")
W("- *API security* — pass on 422 (not 500) for bad input, size/rate limits present, no stack/secret leak, "
  "safe CORS.")
W("- *Communication-protocol security* — pass if messages are signed, expiry/audience/sender verified, "
  "replay de-duplicated, events authenticated.")
W("- *Severity rubric:* Critical = unauthenticated remote action changing safety/booking state or granting "
  "admin on an exposed surface; High = auth/authz bypass or PII/credential exposure needing minimal "
  "preconditions; Medium = control weakness needing a precondition or a defence-in-depth gap; Low = hardening "
  "gap; Informational = observation/production gap. *Impact & likelihood* each scored Low/Medium/High; "
  "**risk = impact × likelihood** (High if product ≥ 6, Medium if ≥ 3, else Low).")
W("")

W("## E. Test cases performed (all 16)")
W("")
for t in tests:
    tf = TF[t["id"]]
    W(f"### {t['id']} — {t['title']}")
    W(f"- **Module / component:** {tf['component']}")
    W(f"- **Area(s):** {', '.join(t['areas'])}")
    W(f"- **Objective:** {t['objective']}")
    W(f"- **Input / attack scenario:** {tf['input']}")
    W(f"- **Expected behaviour:** {tf['expected']}")
    W(f"- **Actual behaviour:** {tf['actual']}")
    W("- **Sub-probes:**")
    W("")
    W("  | # | Probe | Expected | Actual | Result |")
    W("  | --- | --- | --- | --- | --- |")
    for sp in tf["subprobes"]:
        W("  | " + " | ".join(str(x) for x in sp) + " |")
    W("")
    W("  <details><summary>Evidence excerpt (≤ 30 lines, masked)</summary>")
    W("")
    W("  ```")
    for ln in tf["excerpt"].split("\n"):
        W("  " + ln)
    W("  ```")
    W(f"  Full log: `{t['evidence_paths'][0]}`")
    W("  </details>")
    W("")
    W(f"- **Observations:** {tf['observations']}")
    W(f"- **Metrics:** {tf['metrics']}")
    W(f"- **Outcome:** {t['outcome']}. **Linked findings:** {', '.join(t['findings']) or '—'}.")
    W(f"- **Why it succeeded / failed:** {t['why_result']}")
    W(f"- **Rationale for choosing this test:** {t['rationale']}")
    W(f"- **Evidence refs:** {', '.join('`'+p+'`' for p in t['evidence_paths'])}")
    W("")

W("## F. Vulnerabilities identified (register)")
W("")
W("Ordered by severity. `S4-STATIC`-style observations (missing headers, /docs, unsigned events) are "
  "included as Low/Informational only where evidenced.")
W("")
for f in findings:
    ff = FF[f["id"]]
    W(f"### {f['id']} — {f['title']}  ·  **{f['severity']}**")
    W(f"- **Module(s):** {f['modules']}. **Linked tests:** {', '.join(f['linked_tests'])}. "
      f"**Risk:** {f['risk_level']} (impact {f['impact']} × likelihood {f['likelihood']}).")
    W(f"- **Description:** {ff['description']}")
    W(f"- **Evidence:** {ff['evidence']}")
    W(f"- **Technical explanation / root cause:** {ff['root_cause']}")
    W(f"- **Attacker prerequisites:** {ff.get('prerequisites','see description; network reach to the named service.')}")
    W(f"- **Impact (C/I/A + safety + RAI):** {f['impact_description']}")
    W(f"- **Likelihood:** {f['likelihood']} — {ff['likelihood_just']}")
    W(f"- **Severity + justification:** {f['severity']} — {ff['severity_just']}")
    W(f"- **Attack narrative (viva):** {ff.get('narrative','See description; the attacker reaches the named endpoint under the stated prerequisites and obtains the stated impact in a single step.')}")
    W("")

W("## G. Risk assessment")
W("")
W("**Risk matrix (all findings).**")
W("")
W("| Finding | Impact | Likelihood | Risk level |")
W("| --- | --- | --- | --- |")
for f in findings:
    W(f"| {f['id']} {f['title']} | {f['impact']} | {f['likelihood']} | **{f['risk_level']}** |")
W("")
W("**Heatmap as data (impact × likelihood → finding IDs).** See `figures/fig_risk_matrix.png`.")
W("")
cell = {}
for f in findings:
    cell.setdefault((f["impact"], f["likelihood"]), []).append(f["id"])
W("| Impact ↓ / Likelihood → | Low | Medium | High |")
W("| --- | --- | --- | --- |")
for imp in ["High", "Medium", "Low"]:
    row = [f"**{imp}**"]
    for lik in ["Low", "Medium", "High"]:
        ids = cell.get((imp, lik), [])
        rl = "High" if {"Low":1,"Medium":2,"High":3}[imp]*{"Low":1,"Medium":2,"High":3}[lik] >= 6 else ("Medium" if {"Low":1,"Medium":2,"High":3}[imp]*{"Low":1,"Medium":2,"High":3}[lik] >= 3 else "Low")
        row.append((", ".join(ids) + f" *({rl})*") if ids else f"*({rl})*")
    W("| " + " | ".join(row) + " |")
W("")
W("**How risk levels were derived.** Impact and likelihood were each rated Low/Medium/High against the "
  "criteria in §D. Impact weighs confidentiality/integrity/availability plus safety and Responsible-AI harm; "
  "likelihood weighs attacker skill, position (LAN vs authenticated) and preconditions. Risk = impact × "
  "likelihood on a 1–3 scale: product ≥ 6 → High, ≥ 3 → Medium, else Low. The four High-risk findings "
  "(F-01, F-02, F-03, F-16) are all High×High: no skill, LAN reach, immediate impact.")
W("")

W("## H. Mitigation strategies")
W("")
for f in findings:
    m = FF[f["id"]]["mitigation"]
    W(f"### {f['id']} — {f['title']} ({f['severity']})")
    W(f"- **Immediate fix:** {m['immediate']}")
    W(f"- **Long-term / architectural:** {m['long_term']}")
    W(f"- **Specific location:** {m['location']}")
    W(f"- **Example control:** {m['example_control']}")
    W(f"- **Effort:** {m['effort']}. **Retest criterion:** {m['retest']}")
    W("")
W("**Prioritised remediation roadmap.**")
W("- **Now (this week):** F-01 rotate admin password; F-02 remove hard-coded engineer creds; F-03 add auth "
  "on gateway admin/hub routes; F-16 scrub raw NICs + block the read path; F-06 bind gateways to 127.0.0.1.")
W("- **Next (this sprint):** F-05 fail-closed Hub-token verification on receivers; F-04 CORS allowlist; "
  "F-07 multilingual embeddings + relevance threshold; F-09 disable /docs + security headers; F-10 rate limits.")
W("- **Later (architectural):** F-12 per-domain / asymmetric keys; F-13 signed pub/sub events; F-11 signed "
  "session binding; F-08 trust-tier labels on retrieved content; F-14 body-size caps; F-15 numeric-grounding check.")
W("")

W("## I. Reflection inputs")
W("")
W("**Challenges encountered (from this run).**")
W("- LLM/DB latency dominated runtime: M2 pgvector retrieval and the Gemini assistant timed out at 25–90 s "
  "and had to be backgrounded; M1/M4 chat ~2–5 s each; the M1 burst of 20 took 50.4 s.")
W("- Discovering true request schemas (`engineer_id` vs `username`, `question` vs `query`, required "
  "`asset_type`, `severity ∈ {AMBER,RED}`) required reading OpenAPI + code; a wrong field name in Stage 1 "
  "produced two misleading 422 transcripts (M4 login and telemetry), both re-run in Stage 2.")
W("- The M2 assistant never left `rule_based_fallback` despite a present Gemini key, so the number-guard/badge "
  "claims could not be tested on the LLM path.")
W("- Shared Supabase forced write-tests to be `S4TEST_`-scoped and reverted in-script; booking-creation IDOR "
  "was left unexecuted to avoid mutating the bookings table.")
W("- One M2 `model/retrain` fired synchronously during an RBAC probe and retrained the delay model "
  "(metrics byte-identical); disclosed and reverted via `git checkout`.")
W("")
W("**What surprised me (README vs reality).**")
W("- 'Perfect' retrieval (P@1 = 1.000) was an artefact of evaluations whose queries are the indexed text; "
  "independent out-of-corpus P@1 is 0.54 (M1) / 0.875 (M2) / 0.79 (M4).")
W("- Strong signing at the Hub coexists with a public gateway that serves the same admin/hub data unauthenticated.")
W("- The NIC-masking claim is true *and* violated at once: hash+mask are present on every record, yet 8 "
  "passenger objects also still carry the raw NIC.")
W("")
W("**Lessons learned.** Independent, out-of-corpus evaluation is essential to detect metric leakage; "
  "defence-in-depth matters more than any single strong control (the Hub's signing is bypassed by receivers "
  "that don't re-verify it); and a self-audit pass catches real errors (the NIC false-positive was itself a "
  "false conclusion). Verifying request schemas before asserting a result avoids false positives.")
W("")
W("**Future improvements (testing & system).** Testing: adopt these scripts as an automated security "
  "regression suite; force the Gemini path in a controlled run; build a larger multilingual eval set. System: "
  "multilingual embeddings + relevance thresholds; centralised auth at the gateway; per-domain secrets; signed "
  "events; scrub raw identifiers at write.")
W("")

W("## J. README claims vs observed reality")
W("")
W("| README claim | Verdict | Test | Note |")
W("| --- | --- | --- | --- |")
for c in D["readme_claims"]:
    W(f"| {c['claim']} | **{c['verdict']}** | {c['tests']} | {c['note']} |")
W("")

W("## K. Responsible-AI implications")
W("")
W("| RAI dimension | Observation (with numbers) | Test |")
W("| --- | --- | --- |")
W("| **Fairness** | FAQ retrieval P@1 English 1.000 vs Sinhala 0.375 / Tamil 0.250 — the two non-English "
  "languages the product advertises retrieve near-randomly. | S4-M1-01 (F-07) |")
W("| **Transparency / explainability** | Published P@1 = 1.000 is not reproducible independently (0.54–0.875); "
  "M1 chat does label sources (`fares.md`, `via Operations Agent (M2)`); M2 fallback gives no technique badges. | S4-M1-01/02, S4-M2-01/04 |")
W("| **Safety** | M4 engineer assistant corrects a false 2 mm brake premise but emits numeric limits with no "
  "post-hoc grounding check, and answers passenger-scope questions with internal asset data. | S4-M4-02 (F-15) |")
W("| **Accountability** | Hub audit is append-only, records rejected events, and leaks no secrets — actions "
  "are traceable; but default/shared admin credentials undermine attribution. | S4-M3-04, S4-M2-03 (F-01) |")
W("| **Data protection** | NICs are HMAC-hashed and masked on 21/21 objects, yet 8 carry cleartext NIC; the "
  "fraud queue (PII + AI risk labels for 17 people) is served unauthenticated on the public port. | S4-M3-03 (F-16, F-03) |")
W("| **Automated decisioning exposure** | Fraud risk scores/levels (an automated judgement about a named "
  "passenger) are readable without auth — a fairness/appeal concern beyond confidentiality. | S4-M3-03 (F-03) |")
W("")

W("## L. Viva preparation data")
W("")
W("**Per-test: why the attack succeeded/failed (one line each).**")
for t in tests:
    first = t["why_result"].split(". ")[0]
    W(f"- **{t['id']}** ({t['outcome']}): {first}.")
W("")
W("**Per-finding: severity justification + best mitigation (one line each).**")
for f in findings:
    ff = FF[f["id"]]
    W(f"- **{f['id']} ({f['severity']}):** {ff['viva_sev']} → {ff['viva_mit']}")
W("")
W("**System architecture walkthrough (≤ 15 lines).**")
W("1. The browser holds the passenger/officer/engineer token in `localStorage` and calls a gateway "
  "(`frontend/serve.py`, :3000 public / :3001 admin).")
W("2. The gateway either serves an admin/hub route directly (`/api/admin/*`, `/api/hub/*`) or proxies to an "
  "agent via `/svc/{agent}/{path}` (serve.py:167).")
W("3. M1 Passenger (:8001) answers FAQ chat: `retrieve_faq_chunks` (ChromaDB MiniLM) → OpenRouter LLM; live "
  "questions are routed to M2 by intent.")
W("4. M2 Operations (:8005) serves the admin console (RBAC via `admin_auth.py`, tokens signed with "
  "`JWT_SECRET_KEY`), incident management, and the Operations Assistant over pgvector incidents.")
W("5. Inter-agent calls go through the M3 Hub (:8002) `POST /messages`: `verify_agent_token` checks "
  "signature/exp/audience, the Hub checks sender==sub and a static interaction allowlist, de-duplicates by "
  "(sender, message_id), writes an append-only audit row, then routes to the destination.")
W("6. M3 Booking (:8003) and Security (:8004) hold bookings, the fraud queue (NIC hashed+masked) and the "
  "fraud-score model; some `/internal/*` routes trust network placement rather than the Hub token.")
W("7. M4 Maintenance (:8006) serves asset health (local TF-IDF manuals → Groq) and the engineer dashboard "
  "(flag-train behind `x-engineer-token`).")
W("8. Shared state is in Supabase (officers, incidents, bookings, fraud_reviews, 3,900 history rows); alerts "
  "go over Upstash pub/sub as unsigned JSON.")
W("9. Secrets live server-side in `.env`; the browser only ever holds a JWT.")
W("")
W("**10 likely examiner questions with evidence-backed answer notes.**")
qa = [
 ("Why did the Hub reject every forged message but a passenger could still read admin data?",
  "The Hub verifies tokens itself (jwt_utils.py:107-197), but the gateway serves `/api/admin/*` without "
  "calling the Hub or checking a session (serve.py:1840) — different code path, no shared auth. (S4-M3-01 vs S4-M3-03)"),
 ("Why is F-03 High and not Critical?",
  "It is an unauthenticated *read* of PII + risk labels, High×High. Not Critical because no state-changing or "
  "safety action is reached this way and M2's admin API behind the same gateway still returns 401."),
 ("Why did replay protection work when Stage 1 called it inconclusive?",
  "Stage 1's baseline errored at the destination (422) and only 200s are cached (main.py:361-365, 400). Stage 2 "
  "sent a routable delay_check twice: identical 200 and one audit row → dedup proven."),
 ("Why is the M2 retrieval 0.875 when the README says 1.000?",
  "The shipped eval uses corpus notes as queries (evaluate_retrieval.py:3-4) — near-duplicate lookup. "
  "Independent paraphrase/typo queries drop typos to 0.33 and overall to 0.875."),
 ("Is the Sinhala/Tamil gap a bug or a data problem?",
  "Model choice: all-MiniLM-L6-v2 is English-only over an English corpus (retriever.py:15-26), so non-Latin "
  "queries embed near-randomly — a multilingual embedding model fixes it."),
 ("Why did the M4 poisoned note fail to change the answer, but the M2 pending incident leaked?",
  "M4 only injects a report when its MT- ticket id is named (main.py:865); the corpus is the static manual. "
  "M2's assistant tool lists all non-rejected incidents incl. pending (ops_agent_tools.py:184-185)."),
 ("How do you know the default admin password 'worked' without storing it?",
  "`default_login_attempts.json` records status 200 + `login_succeeded:true` and a masked token prefix; the "
  "password itself is masked (Op****) and read from an env var in the script."),
 ("Is the raw-NIC finding real or synthetic test data?",
  "Cannot be determined; treated as PII (F-16). 8/21 passenger objects have a 12-digit nic whose last 4 match "
  "the mask (8/8), created 2026-09-19 — pre-existing rows, not S4TEST."),
 ("Why is CORS only Medium if it reflects any origin with credentials?",
  "Tokens are Bearer headers from localStorage, not cookies, so the browser does not auto-attach them "
  "cross-origin; session theft needs cookie auth. Real misconfig, limited impact today (F-04)."),
 ("What single change most reduces risk?",
  "Authenticate the gateway's admin/hub routes and bind to 127.0.0.1: that closes F-03, most of F-16's "
  "exposure, F-06, and shrinks F-05's reachable surface in one move."),
]
for q, a in qa:
    W(f"- **Q: {q}**  \n  A: {a}")
W("")

W("## M. Evidence & figures manifest")
W("")
W("| Figure / evidence ID | Path | Shows | Used by |")
W("| --- | --- | --- | --- |")
for fg in D["figures"]:
    W(f"| {fg['id']} | `{fg['path']}` | {fg['shows']} | {fg['used_by']} |")
W("")
W("**Manual screenshot checklist (things a CLI cannot capture — the student must take these).**")
W("")
W("| # | URL / action | Login state | Proves | Fills |")
W("| --- | --- | --- | --- | --- |")
W("| 1 | `http://localhost:3000/api/admin/fraud-reviews` in browser | none | unauth PII + risk scores (blur PII) | F-03 / FIG-5 |")
W("| 2 | `http://localhost:3001/login` with default admin creds | none→admin | default admin login (then change) | F-01 |")
W("| 3 | `http://localhost:8005/docs` and `http://localhost:3000/openapi.json` | none | Swagger/API open | F-09 |")
W("| 4 | `http://localhost:3000/api/hub/timeline` | none | unauth hub monitor | F-03 |")
W("| 5 | M2 admin console → Officers/Audit view | admin | RBAC-gated admin UI (contrast to #1) | S4-M2-03 |")
W("| 6 | M1 chat UI showing a cited answer + a Sinhala scope refusal | none | source labels / trilingual UX | S4-M1-02 |")
W("| 7 | M4 engineer dashboard login with hard-coded creds | engineer | F-02 | F-02 |")
W("| 8 | `netstat -ano | findstr \":3000\"` screenshot | — | 0.0.0.0 bind | F-06 |")
W("| 9 | Map page showing only verified incidents | none | public-map gate holds | S4-M2-02 |")
W("| 10 | Hub monitor/audit view after running the M3 test (REJECTED rows) | none | protocol + audit integrity | S4-M3-01/04 |")
W("")

W("## N. Data files")
W("")
W("- `results.json` — complete, valid JSON: `meta`, `environment`, `tests[]` (incl. `why_result`, "
  "`rationale`, `metrics`), `findings[]`, `metrics[]`, `readme_claims[]`, `figures[]`. Validated with "
  "`python -m json.tool`.")
W("- Full evidence transcripts under `evidence/**`; Stage-2 probes under `evidence/stage2_supplementary/`.")
W("")

(A / "REPORT_INPUT_PACK.md").write_text("\n".join(out), encoding="utf-8")
print("REPORT_INPUT_PACK.md lines:", len(out))

# ============================= findings.md =============================
fo = []; F = fo.append
F("# Findings Register — RailSense AI Security & IR Audit (Student 4)")
F("")
F("Severity rubric: **Critical** = unauthenticated remote action changing safety/booking state or granting "
  "admin on an exposed surface; **High** = auth/authz bypass or PII/credential exposure with minimal "
  "preconditions; **Medium** = control weakness needing a precondition or a defence-in-depth gap; **Low** = "
  "hardening gap; **Informational** = observation/production gap. Controls that *held* are recorded in "
  "RESULTS.md and are not inflated into findings. Risk = impact × likelihood (§ risk matrix). "
  "Regenerated in Stage 2 from `results.json`; credentials masked.")
F("")
for f in findings:
    ff = FF[f["id"]]; m = ff["mitigation"]
    F(f"## {f['id']} — {f['title']}")
    F(f"- **Severity: {f['severity']}.** Module(s): {f['modules']}. Tests: {', '.join(f['linked_tests'])}. "
      f"Risk: **{f['risk_level']}** (impact {f['impact']} × likelihood {f['likelihood']}).")
    F(f"- **Description / root cause:** {ff['description']} Root cause: {ff['root_cause']}")
    F(f"- **Evidence:** {ff['evidence']}")
    F(f"- **Impact:** {f['impact_description']}")
    F(f"- **Likelihood:** {f['likelihood']} — {ff['likelihood_just']}")
    F(f"- **Severity justification:** {ff['severity_just']}")
    F(f"- **Mitigation:** *Immediate* — {m['immediate']} *Long-term* — {m['long_term']} (`{m['location']}`; "
      f"e.g. {m['example_control']}; effort {m['effort']}; retest: {m['retest']})")
    F("")
(A / "findings.md").write_text("\n".join(fo), encoding="utf-8")
print("findings.md findings:", len(findings))

# ============================= RESULTS.md =============================
ro = []; R = ro.append
R("# RailSense AI — Security & Information-Retrieval Audit Results")
R(f"### Student 4 · Information Retrieval & Security Assessment · commit `{meta['commit'][:7]}` · "
  f"{meta['testing_window'].split('T')[0]} (Asia/Colombo)")
R("")
R("> Evidence-only hand-off (regenerated in Stage 2 from `results.json`; credentials masked, F-16 added, "
  "S4-M3-01 replay demonstrated, F-08 re-rated Low). Raw transcripts under `evidence/<TEST_ID>/`. Method in "
  "`environment.md`; endpoints in `endpoint_inventory.md`; finding detail in `findings.md`; full report inputs "
  "in `REPORT_INPUT_PACK.md`.")
R("")
R("## 1. Environment & tooling (summary)")
R("Windows 11, Python 3.13.2, Node 24.2.0. All 8 services healthy. Internal agents bind `127.0.0.1`; **both "
  "gateways bind `0.0.0.0`**. LLMs: OpenRouter (M1 **live**), Groq (M4 **live**), Gemini (M2 **rule-based "
  "fallback** at test time). M2 incidents = **pgvector**; M4 manual = **local TF-IDF**. Identities: none / "
  "passenger / operator (gray-box minted + a real S4TEST officer) / admin (documented default). Tools: "
  "`scripts/` (httpx, PyJWT). See `environment.md`.")
R("")
R("## 2. Coverage matrix — 16 tests × 8 Student-4 areas")
R("")
R("| Test | " + " | ".join(areas8) + " | Module |")
R("| --- " + "| :-: " * 8 + "| --- |")
for t in tests:
    row = "".join(" ✔ |" if amap[i] in t["areas"] else " |" for i in range(8))
    R(f"| {t['id']} |" + row + f" {t['module']} |")
R("| **Total** | " + " | ".join(str(sum(1 for t in tests if amap[i] in t["areas"])) for i in range(8)) + " | |")
R("")
R("Every area ≥ 2×; every module = 4 tests.")
R("")
R("## 3. Test summary")
R("")
R("| Test | Module | Area(s) | Outcome | Finding(s) |")
R("| --- | --- | --- | --- | --- |")
for t in tests:
    R(f"| {t['id']} | {t['module']} | {', '.join(t['areas'])} | {t['outcome']} | {', '.join(t['findings']) or '—'} |")
o = meta["outcomes"]
R("")
R(f"**Counts:** PASS {o['PASS']} · PARTIAL {o['PARTIAL']} · FAIL {o['FAIL']} · NOT EXECUTED {o['NOT EXECUTED']}.")
R("")
R("## 4. Result blocks")
R("")
for t in tests:
    tf = TF[t["id"]]
    R(f"### {t['id']} — {t['title']}")
    R(f"- **Component:** {tf['component']}")
    R(f"- **Area(s):** {', '.join(t['areas'])} · **Objective:** {t['objective']}")
    R(f"- **Input:** {tf['input']}")
    R(f"- **Expected:** {tf['expected']}")
    R(f"- **Actual:** {tf['actual']}")
    R("- **Sub-probes:** " + "; ".join(f"{sp[0]}) {sp[1]} → {sp[3]} [{sp[4]}]" for sp in tf["subprobes"]))
    R(f"- **Observations:** {tf['observations']}")
    R(f"- **Outcome:** {t['outcome']}. **Linked:** {', '.join(t['findings']) or 'none'}. "
      f"**Metrics:** {tf['metrics']}. **Evidence:** `{t['evidence_paths'][0]}`")
    R("")
R("## 5. README claims vs observed reality")
R("")
R("| README claim | Verdict | Test | Note |")
R("| --- | --- | --- | --- |")
for c in D["readme_claims"]:
    R(f"| {c['claim']} | **{c['verdict']}** | {c['tests']} | {c['note']} |")
R("")
R("## 6. Findings register (summary — detail in `findings.md`)")
R("")
R("| ID | Title | Module | Severity | Risk | Tests |")
R("| --- | --- | --- | --- | --- | --- |")
for f in findings:
    R(f"| {f['id']} | {f['title']} | {f['modules']} | **{f['severity']}** | {f['risk_level']} | {', '.join(f['linked_tests'])} |")
R("")
R("## 7. Risk matrix")
R("")
R("| Finding | Impact | Likelihood | Risk level |")
R("| --- | --- | --- | --- |")
for f in findings:
    R(f"| {f['id']} {f['title']} | {f['impact']} | {f['likelihood']} | **{f['risk_level']}** |")
R("")
R("See `figures/fig_risk_matrix.png`.")
R("")
R("## 8. Mitigation summary (per finding)")
R("")
for f in findings:
    m = FF[f["id"]]["mitigation"]
    R(f"- **{f['id']} ({f['severity']}):** {m['immediate']} → {m['long_term']} (`{m['location']}`, effort {m['effort']}).")
R("")
R("## 9. S4TEST data & cleanup (re-verified Stage 2)")
R("")
R("| Item | Where | Cleanup | Verified |")
R("| --- | --- | --- | --- |")
R("| 14 incident reports | M2 incidents | admin DELETE | 0 remaining, not on map ✔ |")
R("| 1 officer `s4test_operator@…` | M2 officers.json | deactivated (no delete API) | status inactive ✔ |")
R("| 1 train flag `S4TEST-TRAIN-001` | M4 train_flags | DELETE flag | absent ✔ |")
R("| 2 maintenance reports | M4 field_reports | resolved (no delete API) | text persists, prefixed ✔ |")
R("| Chat sessions A/B, burst | M1 sessions | ephemeral | n/a |")
R("")
R("**Repo state:** no source file modified. Runtime data/log stores changed as a byproduct of authorised "
  "write-tests (M2 `officers.json`, `*_audit_log*.jsonl`, `ops_agent_queries.jsonl`; M4 `field_reports.jsonl`, "
  "`session_tokens.json`, `train_flags.jsonl`); the accidental retrain's two files were reverted. Audit logs "
  "intentionally not reverted (reverting an audit trail is itself tampering). `git status` otherwise shows only "
  "`student4_audit/` as new. Full Stage-2 self-audit: `audit_gaps.md`.")
(A / "RESULTS.md").write_text("\n".join(ro), encoding="utf-8")
print("RESULTS.md lines:", len(ro))
