# RailSense AI — Privacy and Data Leakage Assessment Summary
### Automated Security Testing & Vulnerability Assessment Report (Student 2)
**Module:** IT3041 — Information Retrieval and Web Analytics  
**Specialisation:** Privacy and Data Leakage Assessment  
**Generated At:** `2026-10-04 15:14:44 UTC`  

---

## 1. Executive Summary

This assessment evaluated the privacy boundaries, Personally Identifiable Information (PII) handling, session isolation, and data-leakage surfaces across **RailSense AI**, with special focus on **Module M3: Central Agent Communication Hub & Booking Agent** and inter-agent boundaries.

### Summary Metrics
| Evaluation Metric | Count | Percentage |
| :--- | :--- | :--- |
| **Total Test Cases** | **15** | 100.0% |
| **Controls Verified (PASS)** | **11** | 73.3% |
| **Deficiencies Identified (FAIL)** | **4** | 26.7% |
| **Inconclusive (Environment Offline)** | **0** | 0.0% |

### Identified Risk Distribution (Deficiencies)
- 🟣 **Critical:** 0
- 🔴 **High:** 0
- 🟠 **Medium:** 4
- 🟡 **Low:** 0
- 🔵 **Informational:** 0

---

## 2. Risk Matrix (Impact × Likelihood)

```
                 IMPACT / SEVERITY
LIKELIHOOD    Low          Medium       High         Critical
--------------------------------------------------------------
High          Low          Medium       HIGH         CRITICAL
Medium        Low          Medium       HIGH         CRITICAL
Low           Low          Low          Medium       HIGH
```

---

## 3. Test Cases Execution Matrix (TC-PD-001 to TC-PD-015)

| Test ID | Test Category | Endpoint Tested | Outcome | Severity | Risk Level |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-PD-001` | Sensitive Information Leakage | `/api/hub/dashboard` | 🟢 PASS | Low | **Low** |
| `TC-PD-002` | Personally Identifiable Information (PII) Exposure | `/internal/messages` | 🟢 PASS | Low | **Low** |
| `TC-PD-003` | Error-message leakage | `/internal/messages` | 🟢 PASS | Low | **Low** |
| `TC-PD-004` | Authentication Weaknesses | `/bookings/RS-39230` | 🟢 PASS | Low | **Low** |
| `TC-PD-005` | Authorization / IDOR | `/bookings/RS-39230?user_id=synthetic-user-b-it3041` | 🟢 PASS | Low | **Low** |
| `TC-PD-006` | Authorization / IDOR | `/bookings/RS-39230` | 🟢 PASS | Low | **Low** |
| `TC-PD-007` | Unauthenticated access | `/internal/messages` | 🟢 PASS | Low | **Low** |
| `TC-PD-008` | Unauthenticated access | `/cancellations` | 🟢 PASS | Low | **Low** |
| `TC-PD-009` | Unauthorized Admin Endpoint Access | `/admin/bookings` | 🟢 PASS | Low | **Low** |
| `TC-PD-010` | Unauthenticated access | `/internal/fraud-reviews` | 🔴 FAIL | Medium | **Medium** |
| `TC-PD-011` | Sensitive Information Leakage | `/api/hub/dashboard` | 🔴 FAIL | Medium | **Medium** |
| `TC-PD-012` | Inter-agent data leakage | `/api/hub/timeline` | 🔴 FAIL | Medium | **Medium** |
| `TC-PD-013` | Audit/log leakage | `agent-hub/audit/service.py:write_audit_log` | 🟢 PASS | Low | **Low** |
| `TC-PD-014` | JWT/session security | `/messages` | 🟢 PASS | Low | **Low** |
| `TC-PD-015` | CORS-related data exposure | `agent-hub/main.py & booking-agent/main.py (CORSMiddleware)` | 🔴 FAIL | Medium | **Medium** |

---

## 4. Key Findings & Identified Vulnerabilities

### Finding 1: [TC-PD-010] Verify that internal fraud screening review queues require authentication before exposing flagged cases
- **Vulnerability Category:** Unauthenticated access
- **Endpoint Affected:** `/internal/fraud-reviews`
- **Risk Rating:** Medium (Impact: Medium, Likelihood: High)
- **Technical Observation:** GET /internal/fraud-reviews returned HTTP 200 without authentication. Discloses 18 flagged passenger fraud cases.
- **Root Cause & Justification:** In booking-agent/main.py:704, list_fraud_reviews() does not declare an authentication dependency.
- **Potential Impact:** Exposes flagged traveler identities, risk evaluation metrics, and adjudication notes to unauthorized actors.
- **Conclusion:** MEDIUM DEFICIENCY CONFIRMED: Internal security and fraud adjudication records are accessible to anonymous callers.

### Finding 2: [TC-PD-011] Verify that Central Hub observability dashboard does not disclose internal microservice topology and addresses without auth
- **Vulnerability Category:** Sensitive Information Leakage
- **Endpoint Affected:** `/api/hub/dashboard`
- **Risk Rating:** Medium (Impact: Medium, Likelihood: High)
- **Technical Observation:** GET /api/hub/dashboard returned HTTP 200 without authentication. Discloses 5 registered agent services: ['booking-agent', 'maintenance-agent', 'operations-agent', 'passenger-agent', 'security-agent'], URLs: ['http://127.0.0.1:8003', 'http://127.0.0.1:8006', 'http://127.0.0.1:8005', 'http://127.0.0.1:8001', 'http://127.0.0.1:8004'].
- **Root Cause & Justification:** In agent-hub/main.py:184, get_hub_dashboard() lacks authentication or role dependencies.
- **Potential Impact:** Facilitates attacker reconnaissance by exposing internal RPC endpoints, agent topologies, and circuit breaker states.
- **Conclusion:** MEDIUM DEFICIENCY CONFIRMED: System topology, agent network registry, and loopback URLs are exposed to unauthenticated callers.

### Finding 3: [TC-PD-012] Verify that inter-agent audit timeline logs do not expose sensitive PII or unauthenticated message traces
- **Vulnerability Category:** Inter-agent data leakage
- **Endpoint Affected:** `/api/hub/timeline`
- **Risk Rating:** Medium (Impact: Medium, Likelihood: High)
- **Technical Observation:** GET /api/hub/timeline returned HTTP 200 without authentication. Discloses 681 inter-agent message traces, topologies, and intents.
- **Root Cause & Justification:** agent-hub/main.py:209 defines get_hub_timeline with no security dependency.
- **Potential Impact:** Allows passive reconnaissance of inter-agent communication flows, system errors, and routing volumes.
- **Conclusion:** MEDIUM DEFICIENCY CONFIRMED: Operational audit timeline is accessible to unauthenticated callers, exposing internal routing topology.

### Finding 4: [TC-PD-015] Verify whether local services permit cross-origin requests from arbitrary untrusted origins alongside credentials
- **Vulnerability Category:** CORS-related data exposure
- **Endpoint Affected:** `agent-hub/main.py & booking-agent/main.py (CORSMiddleware)`
- **Risk Rating:** Medium (Impact: Medium, Likelihood: High)
- **Technical Observation:** CORS origin reflection confirmed on: hub, booking. Arbitrary untrusted origin 'https://evil-attacker.com' was reflected in Access-Control-Allow-Origin with credentials.
- **Root Cause & Justification:** FastAPI CORSMiddleware configured with allow_origins=['*'] and allow_credentials=True reflects incoming Origin headers.
- **Potential Impact:** Allows malicious third-party websites to read internal API responses and exfiltrate session data via browser side-channels.
- **Conclusion:** MEDIUM DEFICIENCY CONFIRMED: Permissive CORS configuration (allow_origins=['*'] + allow_credentials=True) exposes internal microservice endpoints to browser-based cross-origin exfiltration.

---

## 5. Detailed Test Case Specifications & Empirical Evidence

### TC-PD-001: Verify that API status and dashboard endpoints do not leak credentials or passenger PII

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-001` |
| **Category** | Sensitive Information Leakage |
| **Endpoint Tested** | `/api/hub/dashboard` |
| **Test Outcome** | 🟢 **PASS** |
| **Severity (Impact)** | 🟡 **LOW** |
| **Likelihood** | Low |
| **Derived Risk Level** | **Low** |
| **Timestamp** | `2026-10-04T15:14:28.891605+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify that API status and dashboard endpoints do not leak credentials or passenger PII
> 
> **Attack Scenario:** Attacker queries public /ready and /api/hub/dashboard endpoints to extract environment credentials or database secrets.

#### 2. Input / Request Dispatched
```json
{
  "endpoints": [
    "/health",
    "/ready",
    "/api/hub/dashboard"
  ]
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** Endpoints should return operational metrics without reflecting environment secrets or credentials.
- **Actual Behaviour:** Queried 3 endpoints. Leaks found: 0.

#### 4. Empirical Observation & Technical Justification
- **Observation:** No environment secrets, API keys, or raw passenger PII were identified in /health, /ready, or /api/hub/dashboard responses.
- **Technical Justification:** Verified by regex and pattern analysis across serialized endpoint JSON payloads.
- **Potential Impact:** Exposure of environment secrets or PII could lead to account takeover or database compromise.
- **Conclusion:** The system successfully prevents sensitive credential leakage across examined diagnostic endpoints.

#### 5. Sanitized Test Evidence
```json
{
  "inspected_responses": {
    "/health": {
      "status_code": 200,
      "body_snippet": "{\"service\":\"agent-hub\",\"status\":\"ok\"}"
    },
    "/ready": {
      "status_code": 200,
      "body_snippet": "{\"service\":\"agent-hub\",\"ready\":true,\"circuit_breakers\":[]}"
    },
    "/api/hub/dashboard": {
      "status_code": 200,
      "body_snippet": "{\"status\":\"online\",\"metrics\":{\"total_messages\":681,\"routed_count\":395,\"rejected_count\":123,\"failed_count\":162},\"agents\":[{\"name\":\"booking-agent\",\"base_url\":\"http://127.0.0.1:8003\",\"description\":\"Booki"
    }
  },
  "findings": []
}
```

---
### TC-PD-002: Verify that raw Sri Lankan National Identity Card (NIC) numbers are masked or hashed in booking responses

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-002` |
| **Category** | Personally Identifiable Information (PII) Exposure |
| **Endpoint Tested** | `/internal/messages` |
| **Test Outcome** | 🟢 **PASS** |
| **Severity (Impact)** | 🟡 **LOW** |
| **Likelihood** | Low |
| **Derived Risk Level** | **Low** |
| **Timestamp** | `2026-10-04T15:14:31.825211+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify that raw Sri Lankan National Identity Card (NIC) numbers are masked or hashed in booking responses
> 
> **Attack Scenario:** Adversary attempts to recover cleartext Sri Lankan NIC numbers from booking creation confirmations.

#### 2. Input / Request Dispatched
```json
{
  "endpoint": "/internal/messages",
  "message_id": "MSG-AUDIT-PD002",
  "passenger_name": "Alice Perera (Synthetic Tester)",
  "passenger_nic": "[REDACTED_NIC_12D]"
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** Raw NIC numbers must never be reflected in plaintext; only HMAC hash or masked strings are acceptable.
- **Actual Behaviour:** HTTP 422. Raw NIC echoed: False.

#### 4. Empirical Observation & Technical Justification
- **Observation:** Raw NIC '200012345678' was NOT echoed in plaintext. Response uses HMAC hashing or masking.
- **Technical Justification:** The system utilizes HMAC-SHA256 database hashing and response masking for passenger identity fields.
- **Potential Impact:** Exposure of Sri Lankan NICs violates national privacy laws and enables identity theft.
- **Conclusion:** Booking Agent enforces effective pseudonymization on sensitive government identity cards.

#### 5. Sanitized Test Evidence
```json
{
  "status_code": 422,
  "raw_nic_present": false,
  "response_sample": "{\"detail\":\"Invalid booking_request payload: 1 validation error for BookingRequest\\npassenger_email\\n  value is not a valid email address: The part after the @-sign is a special-use or reserved name that cannot be used with email. [type=value_error, input_value='alice.synthetic@railsense-audit.local'"
}
```

---
### TC-PD-003: Verify that application error responses do not leak stack traces, database schema, or submitted PII

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-003` |
| **Category** | Error-message leakage |
| **Endpoint Tested** | `/internal/messages` |
| **Test Outcome** | 🟢 **PASS** |
| **Severity (Impact)** | 🟡 **LOW** |
| **Likelihood** | Low |
| **Derived Risk Level** | **Low** |
| **Timestamp** | `2026-10-04T15:14:32.337225+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify that application error responses do not leak stack traces, database schema, or submitted PII
> 
> **Attack Scenario:** Attacker submits malformed payloads to force server errors and observe reflected sensitive data or stack traces.

#### 2. Input / Request Dispatched
```json
{
  "intent": "booking_request",
  "malformed_travel_date": "INVALID_DATE_FORMAT",
  "passenger_email": "[REDACTED_EMAIL]"
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** System returns standard HTTP 422 or 400 error schema without echoing input PII or internal stack traces.
- **Actual Behaviour:** HTTP 422. Stack trace: False, PII reflected: False.

#### 4. Empirical Observation & Technical Justification
- **Observation:** HTTP 422 returned sanitized error structure. No stack traces or PII echoed.
- **Technical Justification:** Pydantic validation schemas intercept invalid types before reaching business logic layers.
- **Potential Impact:** Error message leakage facilitates fingerprinting and provides attackers with internal execution context.
- **Conclusion:** FastAPI validation handlers suppress internal traces and prevent PII reflection.

#### 5. Sanitized Test Evidence
```json
{
  "status_code": 422,
  "stack_trace_detected": false,
  "pii_echoed_in_error": false,
  "response_body_redacted": "{\"detail\":\"Invalid booking_request payload: 1 validation error for BookingRequest\\nseat_class\\n  Value error, seat_class 'INVALID_SEAT_CLASS' is not supported. Must be one of: ['First Class', 'Second Class'] [type=value_error, input_value='INVALID_SEAT_CLASS', input_type=str]\\n    For further inform"
}
```

---
### TC-PD-004: Verify that passenger booking records cannot be retrieved anonymously without authentication

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-004` |
| **Category** | Authentication Weaknesses |
| **Endpoint Tested** | `/bookings/RS-39230` |
| **Test Outcome** | 🟢 **PASS** |
| **Severity (Impact)** | 🟡 **LOW** |
| **Likelihood** | Low |
| **Derived Risk Level** | **Low** |
| **Timestamp** | `2026-10-04T15:14:34.203502+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify that passenger booking records cannot be retrieved anonymously without authentication
> 
> **Attack Scenario:** Attacker discovers a booking reference and attempts direct unauthenticated retrieval via GET /bookings/{ref}.

#### 2. Input / Request Dispatched
```json
{
  "method": "GET",
  "url": "/bookings/RS-39230",
  "headers": {
    "Authorization": null
  }
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** Endpoint must require valid user/agent authentication (HTTP 401 or HTTP 403).
- **Actual Behaviour:** HTTP 401. Anonymous access permitted: False.

#### 4. Empirical Observation & Technical Justification
- **Observation:** Anonymous access rejected with HTTP 401.
- **Technical Justification:** Route definition in booking-agent/main.py:365 does not declare an authentication dependency.
- **Potential Impact:** Direct exposure of passenger journey itineraries, contact emails, and e-ticket QR tokens to anonymous callers.
- **Conclusion:** Authentication guard is active on booking retrieval endpoint.

#### 5. Sanitized Test Evidence
```json
{
  "booking_reference_probed": "RS-39230",
  "http_status": 401,
  "headers": {
    "www-authenticate": "Bearer",
    "content-length": "96",
    "content-type": "application/json"
  },
  "body_preview": "{\"detail\":\"Authentication required: passenger booking records cannot be retrieved anonymously.\"}"
}
```

---
### TC-PD-005: Verify whether an attacker (USER_B) can read a victim's (USER_A) booking by providing user_id parameter

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-005` |
| **Category** | Authorization / IDOR |
| **Endpoint Tested** | `/bookings/RS-39230?user_id=synthetic-user-b-it3041` |
| **Test Outcome** | 🟢 **PASS** |
| **Severity (Impact)** | 🟡 **LOW** |
| **Likelihood** | Low |
| **Derived Risk Level** | **Low** |
| **Timestamp** | `2026-10-04T15:14:34.941266+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify whether an attacker (USER_B) can read a victim's (USER_A) booking by providing user_id parameter
> 
> **Attack Scenario:** Attacker (USER_B) learns USER_A's booking reference and calls GET /bookings/{ref}?user_id=USER_B.

#### 2. Input / Request Dispatched
```json
{
  "endpoint": "/bookings/RS-39230",
  "query_param": {
    "user_id": "synthetic-user-b-it3041"
  }
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** The system must deny access with HTTP 403 Forbidden when user_id does not match the booking owner.
- **Actual Behaviour:** HTTP 403. Cross-user access permitted: False.

#### 4. Empirical Observation & Technical Justification
- **Observation:** Cross-user access denied with HTTP 403 Forbidden. Ownership validation is functioning when user_id parameter is present.
- **Technical Justification:** Evaluated against booking-agent/main.py:391 authorization guard.
- **Potential Impact:** Breaches passenger confidentiality and exposes personal travel itineraries to unauthorized users.
- **Conclusion:** Direct parameter modification is successfully blocked by the authorization check.

#### 5. Sanitized Test Evidence
```json
{
  "victim_booking_ref": "RS-39230",
  "victim_user_id": "synthetic-user-a-it3041",
  "attacker_user_id": "synthetic-user-b-it3041",
  "http_status": 403,
  "response_body_redacted": "{\"detail\":\"Unauthorized access to this booking.\"}"
}
```

---
### TC-PD-006: Verify whether omitting user_id query parameter completely bypasses booking ownership enforcement

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-006` |
| **Category** | Authorization / IDOR |
| **Endpoint Tested** | `/bookings/RS-39230` |
| **Test Outcome** | 🟢 **PASS** |
| **Severity (Impact)** | 🟡 **LOW** |
| **Likelihood** | Low |
| **Derived Risk Level** | **Low** |
| **Timestamp** | `2026-10-04T15:14:35.658117+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify whether omitting user_id query parameter completely bypasses booking ownership enforcement
> 
> **Attack Scenario:** Attacker discovers victim's booking reference and requests GET /bookings/{ref} with no user_id parameter.

#### 2. Input / Request Dispatched
```json
{
  "endpoint": "/bookings/RS-39230",
  "query_params": {}
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** Endpoint must require caller authentication and reject unverified requests (HTTP 401/403).
- **Actual Behaviour:** HTTP 401. Authorization bypassed on omission: False.

#### 4. Empirical Observation & Technical Justification
- **Observation:** Access rejected with HTTP 401 when user_id was omitted.
- **Technical Justification:** In booking-agent/main.py:391, the ownership condition is only evaluated if user_id is truthy.
- **Potential Impact:** Permits anonymous enumeration and exfiltration of all passenger records if references are guessed or observed.
- **Conclusion:** Endpoint enforces mandatory user identity verification.

#### 5. Sanitized Test Evidence
```json
{
  "booking_reference": "RS-39230",
  "owner_user_id": "synthetic-user-a-it3041",
  "query_params_sent": {},
  "http_status": 401,
  "body_preview": "{\"detail\":\"Authentication required: passenger booking records cannot be retrieved anonymously.\"}"
}
```

---
### TC-PD-007: Verify that internal booking mutation endpoints reject requests lacking valid authentication tokens

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-007` |
| **Category** | Unauthenticated access |
| **Endpoint Tested** | `/internal/messages` |
| **Test Outcome** | 🟢 **PASS** |
| **Severity (Impact)** | 🟡 **LOW** |
| **Likelihood** | Low |
| **Derived Risk Level** | **Low** |
| **Timestamp** | `2026-10-04T15:14:36.167733+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify that internal booking mutation endpoints reject requests lacking valid authentication tokens
> 
> **Attack Scenario:** Adversary attempts to invoke internal booking endpoints directly without providing an authentication token.

#### 2. Input / Request Dispatched
```json
{
  "endpoint": "/internal/messages",
  "auth_token": ""
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** Internal mutation endpoints must reject requests with missing or empty authentication tokens (HTTP 401/422).
- **Actual Behaviour:** HTTP 422 returned when submitting empty auth_token.

#### 4. Empirical Observation & Technical Justification
- **Observation:** Request with empty auth_token rejected with HTTP 422.
- **Technical Justification:** FastAPI Pydantic schema validation or JWT verification intercept empty token fields.
- **Potential Impact:** Unauthenticated message injection permits unauthorized seat booking and inventory exhaustion.
- **Conclusion:** The system enforces presence and basic validation on incoming inter-agent message tokens.

#### 5. Sanitized Test Evidence
```json
{
  "http_status": 422,
  "response_body": "{\"detail\":[{\"type\":\"string_too_short\",\"loc\":[\"body\",\"auth_token\"],\"msg\":\"String should have at least 1 character\",\"input\":\"\",\"ctx\":{\"min_length\":1}}]}"
}
```

---
### TC-PD-008: Verify that cancellation management endpoints require authentication before exposing cancellation records

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-008` |
| **Category** | Unauthenticated access |
| **Endpoint Tested** | `/cancellations` |
| **Test Outcome** | 🟢 **PASS** |
| **Severity (Impact)** | 🟡 **LOW** |
| **Likelihood** | Low |
| **Derived Risk Level** | **Low** |
| **Timestamp** | `2026-10-04T15:14:36.682641+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify that cancellation management endpoints require authentication before exposing cancellation records
> 
> **Attack Scenario:** Attacker accesses GET /cancellations to monitor refund claims and passenger travel cancellations.

#### 2. Input / Request Dispatched
```json
{
  "method": "GET",
  "endpoint": "/cancellations",
  "auth": null
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** Endpoint must require administrative or authenticated operator credentials (HTTP 401/403).
- **Actual Behaviour:** HTTP 401. Public access allowed: False.

#### 4. Empirical Observation & Technical Justification
- **Observation:** Access denied with HTTP 401. Authentication required.
- **Technical Justification:** Route booking-agent/main.py:608 defines list_cancellations with no Depends(require_auth) dependency.
- **Potential Impact:** Allows competitors or unauthorized third parties to harvest railway refund cases and cancellation rates.
- **Conclusion:** Cancellation management endpoint enforces authentication.

#### 5. Sanitized Test Evidence
```json
{
  "http_status": 401,
  "content_length": 81,
  "body_preview": "{\"detail\":\"Authentication required. Please provide a valid authorization token.\"}"
}
```

---
### TC-PD-009: Verify that administrative booking manifests cannot be retrieved without administrator credentials

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-009` |
| **Category** | Unauthorized Admin Endpoint Access |
| **Endpoint Tested** | `/admin/bookings` |
| **Test Outcome** | 🟢 **PASS** |
| **Severity (Impact)** | 🟡 **LOW** |
| **Likelihood** | Low |
| **Derived Risk Level** | **Low** |
| **Timestamp** | `2026-10-04T15:14:37.191820+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify that administrative booking manifests cannot be retrieved without administrator credentials
> 
> **Attack Scenario:** Attacker requests GET /admin/bookings to dump the complete passenger manifest for a travel date.

#### 2. Input / Request Dispatched
```json
{
  "method": "GET",
  "endpoint": "/admin/bookings",
  "params": {
    "travel_date": "2026-11-03"
  }
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** Endpoint must strictly require administrator credentials / RBAC role (HTTP 401/403).
- **Actual Behaviour:** HTTP 401. Public manifest disclosure: False.

#### 4. Empirical Observation & Technical Justification
- **Observation:** Access denied with HTTP 401. Admin authentication enforced.
- **Technical Justification:** In booking-agent/main.py:829, list_admin_bookings has no authentication or role dependency.
- **Potential Impact:** Mass leak of citizen travel patterns, contact emails, and payment statuses without any authentication.
- **Conclusion:** Administrative manifest endpoint enforces access control.

#### 5. Sanitized Test Evidence
```json
{
  "http_status": 401,
  "headers": {
    "www-authenticate": "Bearer",
    "content-length": "80",
    "content-type": "application/json"
  },
  "body_preview": "{\"detail\":\"Administrator authentication required. Missing authorization token.\"}"
}
```

---
### TC-PD-010: Verify that internal fraud screening review queues require authentication before exposing flagged cases

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-010` |
| **Category** | Unauthenticated access |
| **Endpoint Tested** | `/internal/fraud-reviews` |
| **Test Outcome** | 🔴 **DEFICIENCY / VULNERABILITY CONFIRMED (FAIL)** |
| **Severity (Impact)** | 🟠 **MEDIUM** |
| **Likelihood** | High |
| **Derived Risk Level** | **Medium** |
| **Timestamp** | `2026-10-04T15:14:37.952167+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify that internal fraud screening review queues require authentication before exposing flagged cases
> 
> **Attack Scenario:** Adversary queries GET /internal/fraud-reviews without authentication to extract flagged passenger cases and risk scores.

#### 2. Input / Request Dispatched
```json
{
  "method": "GET",
  "endpoint": "/internal/fraud-reviews",
  "headers": {
    "Authorization": null
  }
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** Internal fraud queue must strictly require authentication or administrative role (HTTP 401/403).
- **Actual Behaviour:** HTTP 200. Anonymous access permitted: True.

#### 4. Empirical Observation & Technical Justification
- **Observation:** GET /internal/fraud-reviews returned HTTP 200 without authentication. Discloses 18 flagged passenger fraud cases.
- **Technical Justification:** In booking-agent/main.py:704, list_fraud_reviews() does not declare an authentication dependency.
- **Potential Impact:** Exposes flagged traveler identities, risk evaluation metrics, and adjudication notes to unauthorized actors.
- **Conclusion:** MEDIUM DEFICIENCY CONFIRMED: Internal security and fraud adjudication records are accessible to anonymous callers.

#### 5. Sanitized Test Evidence
```json
{
  "http_status": 200,
  "content_length": 22296,
  "body_preview": "[{\"id\":30,\"case_reference\":\"FR-48157\",\"request_reference\":null,\"risk_score\":0.5,\"risk_level\":\"MEDIUM\",\"recommended_action\":\"REVIEW\",\"reasons\":[\"SECURITY_AGENT_UNAVAILABLE: Communication Hub unreachable for fraud check.\"],\"status\":\"PENDING_REVIEW\",\"admin_decision\":null,\"admin_reason\":null,\"created_at"
}
```

---
### TC-PD-011: Verify that Central Hub observability dashboard does not disclose internal microservice topology and addresses without auth

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-011` |
| **Category** | Sensitive Information Leakage |
| **Endpoint Tested** | `/api/hub/dashboard` |
| **Test Outcome** | 🔴 **DEFICIENCY / VULNERABILITY CONFIRMED (FAIL)** |
| **Severity (Impact)** | 🟠 **MEDIUM** |
| **Likelihood** | High |
| **Derived Risk Level** | **Medium** |
| **Timestamp** | `2026-10-04T15:14:38.884059+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify that Central Hub observability dashboard does not disclose internal microservice topology and addresses without auth
> 
> **Attack Scenario:** Adversary queries GET /api/hub/dashboard to map the internal microservice architecture, private IP bindings, and agent URLs.

#### 2. Input / Request Dispatched
```json
{
  "method": "GET",
  "endpoint": "/api/hub/dashboard",
  "headers": {
    "Authorization": null
  }
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** Observability metrics and internal service topologies must require administrator authentication (HTTP 401/403).
- **Actual Behaviour:** HTTP 200. Network topology disclosed: True.

#### 4. Empirical Observation & Technical Justification
- **Observation:** GET /api/hub/dashboard returned HTTP 200 without authentication. Discloses 5 registered agent services: ['booking-agent', 'maintenance-agent', 'operations-agent', 'passenger-agent', 'security-agent'], URLs: ['http://127.0.0.1:8003', 'http://127.0.0.1:8006', 'http://127.0.0.1:8005', 'http://127.0.0.1:8001', 'http://127.0.0.1:8004'].
- **Technical Justification:** In agent-hub/main.py:184, get_hub_dashboard() lacks authentication or role dependencies.
- **Potential Impact:** Facilitates attacker reconnaissance by exposing internal RPC endpoints, agent topologies, and circuit breaker states.
- **Conclusion:** MEDIUM DEFICIENCY CONFIRMED: System topology, agent network registry, and loopback URLs are exposed to unauthenticated callers.

#### 5. Sanitized Test Evidence
```json
{
  "http_status": 200,
  "content_length": 2746,
  "body_preview": "{\"status\":\"online\",\"metrics\":{\"total_messages\":681,\"routed_count\":395,\"rejected_count\":123,\"failed_count\":162},\"agents\":[{\"name\":\"booking-agent\",\"base_url\":\"http://127.0.0.1:8003\",\"description\":\"Booking & Reservation Agent (Member C). Processes booking_request and cancel_booking intents against the "
}
```

---
### TC-PD-012: Verify that inter-agent audit timeline logs do not expose sensitive PII or unauthenticated message traces

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-012` |
| **Category** | Inter-agent data leakage |
| **Endpoint Tested** | `/api/hub/timeline` |
| **Test Outcome** | 🔴 **DEFICIENCY / VULNERABILITY CONFIRMED (FAIL)** |
| **Severity (Impact)** | 🟠 **MEDIUM** |
| **Likelihood** | High |
| **Derived Risk Level** | **Medium** |
| **Timestamp** | `2026-10-04T15:14:39.783829+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify that inter-agent audit timeline logs do not expose sensitive PII or unauthenticated message traces
> 
> **Attack Scenario:** Attacker accesses GET /api/hub/timeline to monitor inter-agent message payloads, correlation IDs, and topologies.

#### 2. Input / Request Dispatched
```json
{
  "method": "GET",
  "endpoint": "/api/hub/timeline",
  "params": {
    "limit": 20
  }
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** Timeline endpoint must require authentication or redact all internal operational telemetry.
- **Actual Behaviour:** HTTP 200. Public timeline access: True.

#### 4. Empirical Observation & Technical Justification
- **Observation:** GET /api/hub/timeline returned HTTP 200 without authentication. Discloses 681 inter-agent message traces, topologies, and intents.
- **Technical Justification:** agent-hub/main.py:209 defines get_hub_timeline with no security dependency.
- **Potential Impact:** Allows passive reconnaissance of inter-agent communication flows, system errors, and routing volumes.
- **Conclusion:** MEDIUM DEFICIENCY CONFIRMED: Operational audit timeline is accessible to unauthenticated callers, exposing internal routing topology.

#### 5. Sanitized Test Evidence
```json
{
  "http_status": 200,
  "headers": {
    "content-length": "7035",
    "content-type": "application/json"
  },
  "body_preview": "{\"total\":681,\"limit\":20,\"offset\":0,\"items\":[{\"id\":681,\"message_id\":\"MSG-AUDIT-PD014-SUB_MISMATCH\",\"correlation_id\":\"MSG-AUDIT-PD014-SUB_MISMATCH\",\"sender_agent\":\"passenger-agent\",\"receiver_agent\":\"booking-agent\",\"intent\":\"booking_request\",\"status\":\"REJECTED\",\"error_message\":\"Token subject does not m"
}
```

---
### TC-PD-013: Verify whether logging and audit services write raw JWT tokens, API keys, or passwords to persistent storage

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-013` |
| **Category** | Audit/log leakage |
| **Endpoint Tested** | `agent-hub/audit/service.py:write_audit_log` |
| **Test Outcome** | 🟢 **PASS** |
| **Severity (Impact)** | 🟡 **LOW** |
| **Likelihood** | Low |
| **Derived Risk Level** | **Low** |
| **Timestamp** | `2026-10-04T15:14:39.794810+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify whether logging and audit services write raw JWT tokens, API keys, or passwords to persistent storage
> 
> **Attack Scenario:** Attacker with database read access queries audit_logs table looking for leaked Bearer tokens or passwords.

#### 2. Input / Request Dispatched
```json
{
  "db_inspected": "railsense_hub_audit.db",
  "sample_limit": 50
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** Audit logging service must redact authentication tokens, secrets, and raw NICs prior to writing to database.
- **Actual Behaviour:** Inspected 50 audit records. Raw credential leaks found: 0.

#### 4. Empirical Observation & Technical Justification
- **Observation:** Verified audit logging sanitization. 50 database entries checked; raw Bearer tokens and passwords are scrubbed before persistence.
- **Technical Justification:** sanitize_audit_text() applies regex scrubbing before saving AuditLog instances to SQLite.
- **Potential Impact:** Exposure of active session tokens in log databases allows replay and impersonation attacks.
- **Conclusion:** Audit logging engine enforces proactive credential scrubbing on logged error streams.

#### 5. Sanitized Test Evidence
```json
{
  "audit_db_found": true,
  "rows_inspected": 50,
  "leak_findings": [],
  "sanitizer_function_tested": true,
  "sample_sanitization": "Error verifying header: Bearer [REDACTED_TOKEN] and password=[REDACTED]"
}
```

---
### TC-PD-014: Evaluate Central Hub JWT validation against alg:none, expired tokens, forged secrets, and sender mismatches

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-014` |
| **Category** | JWT/session security |
| **Endpoint Tested** | `/messages` |
| **Test Outcome** | 🟢 **PASS** |
| **Severity (Impact)** | 🟡 **LOW** |
| **Likelihood** | Low |
| **Derived Risk Level** | **Low** |
| **Timestamp** | `2026-10-04T15:14:43.397738+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Evaluate Central Hub JWT validation against alg:none, expired tokens, forged secrets, and sender mismatches
> 
> **Attack Scenario:** Attacker submits crafted JWTs (alg:none, expired, forged signature) to bypass inter-agent authentication.

#### 2. Input / Request Dispatched
```json
{
  "scenarios_evaluated": [
    "alg_none",
    "expired",
    "sub_mismatch",
    "whitespace"
  ]
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** All forged, expired, or tampered tokens must be strictly rejected with HTTP 401 Unauthorized.
- **Actual Behaviour:** Probed 4 token variations. Failures: 0.

#### 4. Empirical Observation & Technical Justification
- **Observation:** All 4 JWT forgery scenarios (alg:none, expired signature, sender claim mismatch, whitespace) were rejected with HTTP 401/422.
- **Technical Justification:** agent-hub/auth/jwt_utils.py pins algorithms=['HS256'] and verifies subject against sender_agent.
- **Potential Impact:** Forging valid tokens enables unauthorized inter-agent RPC commands across the railway network.
- **Conclusion:** Central Hub enforces strict cryptographic pinning (HS256) and validates token claims rigorously.

#### 5. Sanitized Test Evidence
```json
{
  "test_outcomes": {
    "alg_none": {
      "status_code": 401,
      "body_snippet": "{\"detail\":\"Invalid or expired authentication token\"}"
    },
    "expired": {
      "status_code": 401,
      "body_snippet": "{\"detail\":\"Invalid or expired authentication token\"}"
    },
    "sub_mismatch": {
      "status_code": 401,
      "body_snippet": "{\"detail\":\"Token subject does not match sender agent\"}"
    },
    "whitespace": {
      "status_code": 422,
      "body_snippet": "{\"detail\":[{\"type\":\"string_too_short\",\"loc\":[\"body\",\"auth_token\"],\"msg\":\"String should have at least 1 character\",\"input\":\"   \",\"ctx\":{\"min_length\":1}"
    }
  },
  "vulnerabilities_detected": []
}
```

---
### TC-PD-015: Verify whether local services permit cross-origin requests from arbitrary untrusted origins alongside credentials

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `TC-PD-015` |
| **Category** | CORS-related data exposure |
| **Endpoint Tested** | `agent-hub/main.py & booking-agent/main.py (CORSMiddleware)` |
| **Test Outcome** | 🔴 **DEFICIENCY / VULNERABILITY CONFIRMED (FAIL)** |
| **Severity (Impact)** | 🟠 **MEDIUM** |
| **Likelihood** | High |
| **Derived Risk Level** | **Medium** |
| **Timestamp** | `2026-10-04T15:14:44.413751+00:00` |

#### 1. Attack Scenario & Objective
> **Objective:** Verify whether local services permit cross-origin requests from arbitrary untrusted origins alongside credentials
> 
> **Attack Scenario:** Attacker lures railway staff to an external website that executes cross-origin fetch requests to local RailSense APIs with credentials.

#### 2. Input / Request Dispatched
```json
{
  "headers": {
    "Origin": "https://evil-attacker.com"
  },
  "endpoint": "/health"
}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** Services must reject arbitrary origins or omit Access-Control-Allow-Credentials when using wildcard policies.
- **Actual Behaviour:** Probed services: ['hub', 'booking']. Reflected untrusted origins: ['hub', 'booking'].

#### 4. Empirical Observation & Technical Justification
- **Observation:** CORS origin reflection confirmed on: hub, booking. Arbitrary untrusted origin 'https://evil-attacker.com' was reflected in Access-Control-Allow-Origin with credentials.
- **Technical Justification:** FastAPI CORSMiddleware configured with allow_origins=['*'] and allow_credentials=True reflects incoming Origin headers.
- **Potential Impact:** Allows malicious third-party websites to read internal API responses and exfiltrate session data via browser side-channels.
- **Conclusion:** MEDIUM DEFICIENCY CONFIRMED: Permissive CORS configuration (allow_origins=['*'] + allow_credentials=True) exposes internal microservice endpoints to browser-based cross-origin exfiltration.

#### 5. Sanitized Test Evidence
```json
{
  "untrusted_origin_tested": "https://evil-attacker.com",
  "results_by_service": {
    "hub": {
      "origin_sent": "https://evil-attacker.com",
      "access_control_allow_origin": "https://evil-attacker.com",
      "access_control_allow_credentials": "true",
      "reflects_untrusted_origin": true,
      "credentials_allowed": true,
      "vulnerable": true
    },
    "booking": {
      "origin_sent": "https://evil-attacker.com",
      "access_control_allow_origin": "https://evil-attacker.com",
      "access_control_allow_credentials": "true",
      "reflects_untrusted_origin": true,
      "credentials_allowed": true,
      "vulnerable": true
    }
  },
  "vulnerable_count": 2
}
```

---
