# Stage-2 Self-Audit of Stage-1 Output — Student 4

Audit of `student4_audit/` (Stage 1) against the assignment's testing requirements and marking
rubric. Every PASS/FAIL below is checked against files on disk. Gaps that could be closed were
closed with bounded supplementary probes (`scripts/supp_stage2.py`, evidence under
`evidence/stage2_supplementary/`); the rest are listed under **Unresolved**.

Re-tested commit `8b66312`, services healthy, 2026-09-29 (Asia/Colombo).

---

## 1. Test count and structure — PASS (with 2 fixed evidence gaps)

- Exactly 16 test blocks S4-M1-01 … S4-M4-04, each with the 8 required fields (Test ID, Objective,
  Input/Attack, Expected, Actual, Evidence, Observations, Outcome), a non-empty Actual, an Outcome,
  and ≥ 1 evidence file that exists on disk.
- **Verified every evidence path** referenced in `RESULTS.md`/`results.json`: all 30 `evidence/**`
  files resolve; no broken paths. (Checked with a path-existence scan.)
- **Fixed — 2 stale transcripts** where the Stage-1 script used the wrong request schema, so the
  saved Actual reflected a 422 schema error rather than the real behaviour:
  - **S4-M4-03 engineer login:** Stage-1 `test_m4_03_api.py` posted `{"username":…}` (correct field is
    `engineer_id`), giving 422 and `got_token=false` in `evidence/S4-M4-03/results.json`, which
    contradicted the finding text (F-02 said login succeeded). Re-run with the correct schema
    (`supp_stage2.py` G1): **200, token issued, eng_id ENG-001**; wrong-password control **401**.
    Finding F-02 now matches its evidence.
  - **S4-M4-03 telemetry fuzz:** the Stage-1 `/asset-health` fuzz omitted the required `asset_type`,
    so all 7 cases returned 422 at the wrong validator. Re-run with a valid `asset_type` (G2, 11
    cases): numeric-bound/type/enum errors correctly 422, free-form `sensors` dict tolerates
    NaN/inf/5000 keys with 200 and **no 500s**. Conclusion (input validation solid, no crashes) is
    unchanged and now properly evidenced.

## 2. Thin tests — PASS (with 1 fixed)

- Sub-probe counts: all 16 tests carry ≥ 3 sub-probes; 13 carry ≥ 4. The three with exactly 3
  (S4-M4-04, and the retrieval tests' category rows) are backed by 24-item metric sets, so they are
  not thin.
- Metrics present where expected: S4-M1-01 (P@1/P@3/MRR + per-language, n=24), S4-M2-01 (P@1/P@3/P@5/MRR,
  n=24), S4-M4-01 (P@1/P@3/P@5/MRR, n=24). Sample sizes stated.
- **Fixed — S4-M3-01 replay/dedup** was the one under-evidenced probe: Stage 1 marked it "inconclusive"
  because the baseline message errored at the destination (422), and only 200 responses are cached, so
  dedup never triggered. Re-run (G3) with a routable read-only `delay_check` (train PM-8056 named in
  `raw_text`): first send 200 routed, second send 200 with an **identical body and exactly one audit
  row** — dedup demonstrated at runtime. S4-M3-01 outcome upgraded from "PASS (dedup by code only)" to
  a fully demonstrated PASS.
- No test has an Outcome of NOT EXECUTED. Two **sub-probes** remain not-executed by design (see
  Unresolved): booking-creation IDOR and the dead-receiver circuit breaker.

## 3. Coverage — PASS

Re-derived from the result blocks (see `figures/fig_coverage_matrix.png`, generated from the data):

| Area | Count | Tests |
| --- | :-: | --- |
| Retrieval Accuracy | 3 | M1-01, M2-01, M4-01 |
| Retrieval Manipulation | 2 | M2-02, M4-04 |
| Hallucination due to Retrieval | 3 | M1-02, M2-04, M4-02 |
| Source Reliability | 6 | M1-02, M2-02, M2-04, M3-04, M4-02, M4-04 |
| Authentication | 5 | M1-03, M2-03, M3-01, M3-02, M4-03 |
| Authorization | 5 | M1-03, M2-03, M3-01, M3-03, M4-03 |
| API Security | 6 | M1-04, M2-03, M3-02, M3-03, M3-04, M4-03 |
| Communication Protocol Security | 5 | M1-04, M3-01, M3-02, M3-04, M4-03 |

Every area ≥ 2; every module = 4 tests. 16 tests total (≥ 15 required).

## 4. Findings quality — PASS (register expanded 15 → 16)

- Every finding has description, evidence path, impact, likelihood, severity + justification, risk
  level, root cause with file:line, and mitigation. Root-cause file:line re-verified against source
  this session (e.g. `admin_db.py:444-445`, M4 `main.py:74-79/120-122/846-847`, `serve.py:1840/2454/2460`,
  `security-agent/main.py:99-105`, `ops_agent_tools.py:184-185`, `review_service.py:99`).
- **Passes now state why the control held**, with mechanism + file:line (added to the "why it
  succeeded/failed" field of every test in `REPORT_INPUT_PACK.md` §E and `results.json`): e.g. Hub token
  attacks rejected by `verify_agent_token` (jwt_utils.py:107-197) pinning algorithms and checking
  aud/sub; RBAC held via server-side role checks + `jwt.decode(..., algorithms=[JWT_ALGORITHM])`.
- **Severity re-calibrated, no inflation:**
  - **F-08** (pending incidents reach Ops Assistant) lowered **Medium → Low**: listing the review queue
    to officers is intended behaviour, the item is labelled `_pending_`, and no manipulated answer was
    produced (Gemini path not live). The residual issue (unsanitised untrusted text) is real but low.
  - **F-15** kept **Informational**: no incorrect safety number was demonstrated; the emitted brake
    figures match the manual section seen in S4-M4-04.
  - **F-12** kept **Medium (design)**: large blast radius but requires a secret leak (likelihood Low).
  - No finding's severity rests on a vague justification; each severity line names why it is not one
    level higher (e.g. F-01 "not Critical because LAN-only and no safety-state path").
- **New finding F-16 (High)** created from a corrected Stage-1 conclusion (see item 5).

## 5. Negative-result honesty — PASS (with 1 important correction)

- Failed attacks are reported as PASS/control-held, not omitted: token forgeries (S4-M2-03), Hub
  protocol attacks (S4-M3-01), NIC masking presence (S4-M3-03), map-feed gate and HTML rejection
  (S4-M2-02), poisoned notes not reaching the M4 answer (S4-M4-04), no-fabrication in assistants
  (S4-M1-02, S4-M2-04, S4-M4-02). Each is now backed by a stated mechanism.
- **Corrected over-optimistic Stage-1 claim (NIC).** Stage 1 recorded the NIC-cleartext regex hit in
  S4-M3-03 as a *false positive* (12-digit run inside a hash). Re-checking with a **hex-bounded regex
  plus a last-4-digits-vs-mask comparison** (G4 + `nic_raw_field_check.json`) shows the original hit was
  **partly real**: 8 of 21 passenger objects (4 of 17 fraud cases) carry a raw 12-digit `nic` field
  whose last four digits match `nic_masked` (8/8) — i.e. genuine cleartext NIC alongside the hash/mask.
  This is now **F-16 (High)**, and the S4-M3-03 sub-probe "no cleartext NIC" is changed from pass to
  **fail**. The masking control still *exists* (hash + mask present on 21/21 objects); the defect is a
  legacy/helper write path that also stored the raw value. This is the one place Stage 1 under-reported
  a finding; it is corrected rather than buried.

## 6. Secrets scan — PASS (after masking)

Grepped every file under `student4_audit/` for `eyJ`, `sk-`, `gsk_`, `AIza`, `postgresql://`, `SUPABASE`,
`Bearer <20+>`, and each concrete value from `.env` / `M4/.env`.

- No live JWT/API-key/DB-URI/Bearer material in any output. Tokens appear only as masked prefixes
  (`eyJhbGciOiJI…`, `b14f96…[MASKED]`) via the harness scrubber.
- `SUPABASE` appears once, in `environment.md`, as a **key name only** (presence table), no value.
- One `.env` value (`SECURITY_AGENT_URL`, `http://127.0.0.1:8004`) appears in `recon_summary.json`. This
  is a localhost service URL, not a secret; left as-is (it is public topology already in the finding
  text).
- **Masked the two documented passwords** that Stage 1 had left in cleartext inside the *scripts*:
  `scripts/_harness.py`, `try_default_login.py` and the M4 test scripts now read them from environment
  variables (`S4_ADMIN_PW`, `S4_M4_ENG_PW`) instead of literals, and the evidence key that had embedded the
  password string was renamed to `hardcoded_admin_login`. **Note:** `RESULTS.md` and `findings.md` (Stage-1 files) still quote the two passwords in
  their finding descriptions; `REPORT_INPUT_PACK.md` masks them (`Op****`, `ad****`). Decide per your
  submission whether the report itself should name them — the pack is written masked so it is safe to
  hand to the writer as-is.

## 7. Cleanup — PASS (re-verified this session)

`S4TEST_` objects created and their confirmed disposal (final query in G6):

| Object | Where | Disposal | Re-verified now |
| --- | --- | --- | --- |
| 14 incident reports | M2 incidents (Supabase) | admin DELETE | `S4TEST` count in `/incidents` = **0**; map-feed = 0 |
| 1 officer `s4test_operator@…` | M2 officers.json | deactivated (no delete API) | present, **status inactive** |
| 1 train flag `S4TEST-TRAIN-001` | M4 train_flags | DELETE flag | `/trains-under-maintenance` `S4TEST` = **0** |
| 2 maintenance reports | M4 field_reports.jsonl | resolved (no delete API) | 2 rows persist, text only, prefixed `S4TEST_` |
| Chat sessions A/B, burst | M1 sessions | ephemeral | n/a |

**Two supplementary artefacts were created in Stage 2 and are non-mutating or reverted:** G1 issued one
M4 engineer session token (logout endpoint absent → token expires with the process; no persistent
object); G3 sent a routable `delay_check` (read-only) that added audit rows to the Hub timeline (audit is
append-only by design and legitimately records the test).

`git status` shows only `student4_audit/` as untracked plus the same runtime data/log files changed as a
byproduct of Stage-1 authorised write-tests (M2 `officers.json`, `*_audit_log*.jsonl`,
`ops_agent_queries.jsonl`; M4 `field_reports.jsonl`, `session_tokens.json`, `train_flags.jsonl`;
`M2 ui/index.html`, `start.py`). **No source file was modified by this audit.** Audit-log files are
intentionally not reverted (reverting an audit trail is itself tampering).

---

## Unresolved (left as documented limitations, per the ground rules)

1. **M2 Operations Assistant Gemini path (S4-M2-04).** Ran in `rule_based_fallback` throughout despite
   `GEMINI_API_KEY` being present, so the README's number-guard and technique-badge claims could not be
   exercised on the LLM path. Not forced live to avoid external-provider calls/quota. **Word in report
   as:** verified for the deterministic fallback (no fabrication); LLM-path grounding untested.
2. **Booking-creation IDOR (S4-M3-03 sub-probe e).** "Cancel passenger B's booking as A" needs a real
   booking created in the shared bookings table; left NOT EXECUTED to avoid mutating shared data. NIC
   masking/exposure and the access-control matrix were still fully tested via existing records.
3. **Dead-receiver circuit breaker (S4-M3-04 sub-probe g).** The static registry has no dead agent to
   target; breaker states were read from `/ready` instead of forced open. Bounded-scope limitation.
4. **F-15 safety-number grounding.** The M4 assistant's brake/temperature figures were not diff-checked
   against the manual text within this audit (would require parsing the manual corpus and the model's
   citations). Observed figures are consistent with the manual section returned in S4-M4-04, but
   "grounded" is asserted only weakly. Kept Informational.
5. **Passwords in Stage-1 `RESULTS.md`/`findings.md`.** Left in place there (they are the substance of
   F-01/F-02); masked in the report pack. Your call whether the final report names them.
