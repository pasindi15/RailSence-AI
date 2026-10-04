# RailSense AI — Privacy & Data Leakage Assessment Toolkit

**University Assignment:** IT3041 — Information Retrieval and Web Analytics  
**Assigned Specialisation:** Student 2 — Privacy and Data Leakage Assessment  
**Target System:** RailSense AI Multi-Agent Railway Assistant (Central Agent Hub & Booking Agent)  

---

## 1. Overview & Assessment Scope

This automated security assessment toolkit was constructed to perform an independent, objective evaluation of the privacy boundaries, personally identifiable information (PII) handling, session isolation, and data-leakage surfaces across **RailSense AI**.

The toolkit operates as a safe, non-destructive external auditor. It evaluates 15 independent test cases targeting architectural vulnerabilities without modifying application source code or attacking production environments.

### Core Assessment Areas
1. **Sensitive Information Leakage:** Diagnostic probes against status, ready, and observability dashboards.
2. **Personally Identifiable Information (PII) Exposure:** Evaluation of Sri Lankan National Identity Card (NIC) handling, phone numbers, and passenger emails.
3. **Conversation Memory Leakage:** Isolation of conversational context within chat agents.
4. **Authentication Weaknesses:** Verification of token requirements across state-mutating endpoints.
5. **Authorization / IDOR:** Insecure Direct Object References in booking retrieval via parameter manipulation and omission.
6. **User Data Protection:** Analysis of passenger travel histories, booking references, and manifest security.
7. **API Response Leakage:** Inspection of serialized JSON payloads for unexpected internal fields.
8. **Error-Message Leakage:** Validation error handling and prevention of stack trace disclosures.
9. **Inter-Agent Data Leakage:** Inspection of routed message payloads across communication channels.
10. **Audit/Log Leakage:** Verification of token and secret scrubbing in database audit tables.
11. **JWT / Session Security:** Cryptographic pinning, expiry enforcement, and tampering resilience.
12. **Privacy-Related Configuration Weaknesses:** Fallback secrets and insecure configuration flags.
13. **CORS-Related Data Exposure:** Permissive origin reflection and credential exposure.
14. **Unauthenticated Access:** Public availability of sensitive operational and management queues.
15. **Cross-User Data Access:** Tenancy separation between synthetic test callers.

---

## 2. Architecture Map & Target Endpoints

| Architectural Component | Port / Interface | Target Endpoints | Primary Security / Privacy Concern |
| :--- | :--- | :--- | :--- |
| **Central Agent Hub (M3)** | `:8002` (FastAPI) | `/messages`, `/ready`, `/health`, `/api/hub/dashboard`, `/api/hub/timeline` | JWT validation, message route authorization, audit timeline exposure, CORS reflection. |
| **Booking Agent (M3)** | `:8003` (FastAPI) | `/bookings/{ref}`, `/admin/bookings`, `/cancellations`, `/internal/fraud-reviews`, `/internal/messages` | Missing authentication dependencies, IDOR in booking lookup, full passenger manifest exposure. |
| **Passenger Assistant (M1)**| `:8001` (FastAPI) | `/chat`, `/chat/{session_id}/history`, `/chat` (list) | Unauthenticated session history retrieval, global session enumeration, conversational memory leakage. |
| **Operations Agent (M2)** | `:8005` (FastAPI) | `/passenger/query`, `/admin/auth/login`, `/health` | RBAC validation, cross-origin reflection with credentials. |
| **Maintenance Agent (M4)** | `:8006` (FastAPI) | `/health`, `/api/assets`, `/chat` | Microservice boundary isolation and CORS policy. |

---

## 3. Toolkit Architecture

```
privacy_assessment/
├── README.md                 # Complete documentation and assessment guide
├── config.py                 # Endpoint configuration, synthetic test data, risk matrix
├── pii_scanner.py            # Automated Sri Lankan NIC, email, JWT, and secret regex scanner
├── test_cases.py             # TestCaseResult data model, JSON/CSV/Markdown serialisation
├── test_runner.py            # Master test orchestrator and CLI reporting suite
├── api_leakage_tests.py      # TC-PD-001, TC-PD-002, TC-PD-003
├── auth_tests.py             # TC-PD-004, TC-PD-007, TC-PD-014
├── authorization_tests.py    # TC-PD-005, TC-PD-006, TC-PD-008, TC-PD-009
├── memory_tests.py           # TC-PD-010, TC-PD-011
├── log_leakage_tests.py      # TC-PD-012, TC-PD-013
├── cors_tests.py             # TC-PD-015
├── evidence/                 # Individual sanitized JSON test evidence files
├── results/                  # Aggregate results: JSON, CSV, and Markdown report
└── report_data/              # Visual diagrams and tabular summary data
```

---

## 4. Test Case Catalog (15 Independent Security Tests)

| Test ID | Category | Objective | Target Endpoint |
| :--- | :--- | :--- | :--- |
| **TC-PD-001** | Sensitive Information Leakage | Verify status and dashboard APIs do not leak environment credentials | `/api/hub/dashboard` |
| **TC-PD-002** | PII Exposure | Verify raw Sri Lankan NICs are masked or hashed in booking confirmations | `/internal/messages` |
| **TC-PD-003** | Error-Message Leakage | Verify error bodies do not echo submitted PII or expose stack traces | `/internal/messages` |
| **TC-PD-004** | Authentication Weakness | Test whether passenger booking records can be retrieved anonymously | `/bookings/{booking_reference}` |
| **TC-PD-005** | Authorization / IDOR | Test if USER_B can access USER_A's booking by passing `user_id` query param | `/bookings/{ref}?user_id={id}` |
| **TC-PD-006** | Authorization / IDOR | Test if omitting `user_id` completely bypasses booking ownership enforcement | `/bookings/{booking_reference}` |
| **TC-PD-007** | Unauthenticated Access | Verify internal booking mutation endpoints reject empty/missing auth tokens | `/internal/messages` |
| **TC-PD-008** | Unauthenticated Access | Test if cancellation requests and refund claims are exposed without auth | `/cancellations` |
| **TC-PD-009** | Unauthorized Admin Access | Test if passenger manifests can be retrieved without administrator role | `/admin/bookings` |
| **TC-PD-010** | Conversation Memory Leakage | Test if chat history containing PII can be queried without authentication | `/chat/{session_id}/history` |
| **TC-PD-011** | Cross-Session Data Leakage | Test whether chat session listing leaks cross-user session titles | `/chat` |
| **TC-PD-012** | Inter-Agent Data Leakage | Verify whether Hub audit timeline exposes inter-agent message traces | `/api/hub/timeline` |
| **TC-PD-013** | Audit / Log Leakage | Verify audit logs redact Bearer tokens and passwords before persistence | `agent-hub/audit/service.py` |
| **TC-PD-014** | JWT / Session Security | Evaluate token validation against alg:none, expiry, and forged signatures | `/messages` |
| **TC-PD-015** | CORS Data Exposure | Verify whether arbitrary untrusted origins are reflected with credentials | `CORSMiddleware` |

---

## 5. Safety Protocols & Synthetic PII Guarantees

In strict compliance with academic research ethics and the **Sri Lanka Personal Data Protection Act (PDPA) No. 9 of 2022**:
1. **Local Test Environment Only:** The toolkit exclusively targets localhost (`127.0.0.1`) interfaces.
2. **Synthetic Data Exclusively:** All tests utilize isolated synthetic test accounts:
   - Synthetic User A: `synthetic-user-a-it3041` (`alice.synthetic@railsense-audit.local`, NIC: `200012345678`)
   - Synthetic User B: `synthetic-user-b-it3041` (`bob.synthetic@railsense-audit.local`, NIC: `199512345670`)
3. **No Real PII:** No actual human personal identity records or production database entries are manipulated.
4. **Credential Redaction:** The automated PII scanner actively redacts JWT tokens, passwords, and identity markers before persisting evidence to disk.
5. **Non-Destructive:** Probes do not corrupt or purge operational schedules or valid application records.

---

## 6. Execution Instructions

### Running the Complete Assessment Suite
From the repository root:
```powershell
python privacy_assessment/test_runner.py
```

### Generated Output Artifacts
Upon test completion, three structured report files are automatically generated:
- `privacy_assessment/results/privacy_results.json`: Complete machine-readable assessment dataset.
- `privacy_assessment/results/privacy_results.csv`: Excel-ready tabular summary for risk matrices and quantitative reporting.
- `privacy_assessment/results/privacy_summary.md`: Formatted human-readable report with detailed evidence breakdowns.
- `privacy_assessment/evidence/*.json`: Individual test case raw JSON evidence snapshots with redacted credentials.
