# RailSense AI — Endpoint Inventory (Student 4 audit)

Generated 2026-09-28T19:12:47.123397+05:30 from live /openapi.json on each service + code review.

Auth column: VERIFIED = confirmed by dynamic test; FINDING = missing/weak control confirmed.

## gateway_user (port 3000) — /docs exposed: True

| Method | Path | Auth (intended/observed) |
| --- | --- | --- |
| GET | /api/train-board | unknown/none |
| POST | /api/auth/login | unknown/none |
| POST | /api/auth/logout | unknown/none |
| GET | /api/auth/me | unknown/none |
| POST | /api/chat | none (M1 public; M4 engineer-token) |
| GET | /api/booking-options | unknown/none |
| POST | /api/bookings/confirm | unknown/none |
| POST | /api/cancellations/confirm | unknown/none |
| GET | /api/admin/cancellations | NONE via gateway - FINDING |
| POST | /api/admin/cancellations/{case_reference}/review | NONE via gateway - FINDING |
| POST | /api/admin/cancellations/nlp-preview | NONE via gateway - FINDING |
| GET | /api/admin/trains | unknown/none |
| GET | /api/admin/bookings | unknown/none |
| GET | /api/admin/fraud-reviews | NONE via gateway - FINDING |
| POST | /api/admin/fraud-reviews/{case_reference}/review | NONE via gateway - FINDING |
| GET | /api/admin/system-health | NONE on port 3000 - FINDING |
| GET | /api/hub/dashboard | NONE - FINDING |
| GET | /api/hub/timeline | NONE - FINDING |
| GET | /api/tickets/verify/{ticket_token} | unknown/none |
| GET | /api/tickets/{booking_reference} | unknown/none |
| POST | /api/holds | unknown/none |
| POST | /api/waiting-list | unknown/none |
| POST | /api/admin/booking-chat | unknown/none |

## gateway_admin (port 3001) — /docs exposed: True

| Method | Path | Auth (intended/observed) |
| --- | --- | --- |
| GET | /api/train-board | unknown/none |
| POST | /api/auth/login | unknown/none |
| POST | /api/auth/logout | unknown/none |
| GET | /api/auth/me | unknown/none |
| POST | /api/chat | none (M1 public; M4 engineer-token) |
| GET | /api/booking-options | unknown/none |
| POST | /api/bookings/confirm | unknown/none |
| POST | /api/cancellations/confirm | unknown/none |
| GET | /api/admin/cancellations | NONE via gateway - FINDING |
| POST | /api/admin/cancellations/{case_reference}/review | NONE via gateway - FINDING |
| POST | /api/admin/cancellations/nlp-preview | NONE via gateway - FINDING |
| GET | /api/admin/trains | unknown/none |
| GET | /api/admin/bookings | unknown/none |
| GET | /api/admin/fraud-reviews | NONE via gateway - FINDING |
| POST | /api/admin/fraud-reviews/{case_reference}/review | NONE via gateway - FINDING |
| GET | /api/admin/system-health | NONE on port 3000 - FINDING |
| GET | /api/hub/dashboard | NONE - FINDING |
| GET | /api/hub/timeline | NONE - FINDING |
| GET | /api/tickets/verify/{ticket_token} | unknown/none |
| GET | /api/tickets/{booking_reference} | unknown/none |
| POST | /api/holds | unknown/none |
| POST | /api/waiting-list | unknown/none |
| POST | /api/admin/booking-chat | unknown/none |

## m1 (port 8001) — /docs exposed: True

| Method | Path | Auth (intended/observed) |
| --- | --- | --- |
| GET | /health | unknown/none |
| GET | /trains/{train_id}/details | unknown/none |
| GET | /chat | none (M1 public; M4 engineer-token) |
| POST | /chat | none (M1 public; M4 engineer-token) |
| GET | /chat/{session_id}/history | none (M1 public; M4 engineer-token) |
| DELETE | /chat/{session_id} | none (M1 public; M4 engineer-token) |
| PATCH | /chat/{session_id}/title | none (M1 public; M4 engineer-token) |
| PATCH | /chat/{session_id}/pin | none (M1 public; M4 engineer-token) |
| POST | /feedback | unknown/none |

## hub (port 8002) — /docs exposed: True

| Method | Path | Auth (intended/observed) |
| --- | --- | --- |
| GET | /health | unknown/none |
| GET | /ready | unknown/none |
| POST | /register | unknown/none |
| GET | /api/hub/dashboard | NONE - FINDING |
| GET | /api/hub/timeline | NONE - FINDING |
| POST | /messages | agent JWT (verify_agent_token) - VERIFIED |

## booking (port 8003) — /docs exposed: True

| Method | Path | Auth (intended/observed) |
| --- | --- | --- |
| GET | /health | unknown/none |
| GET | /booking-options | unknown/none |
| POST | /internal/messages | agent JWT (verify_agent_token) - VERIFIED |
| GET | /bookings/{booking_reference} | unknown/none |
| POST | /internal/seat-holds | none independent (schema only) - FINDING |
| POST | /internal/waiting-list | none independent (schema only) - FINDING |
| GET | /internal/waiting-list/{queue_id} | none independent (schema only) - FINDING |
| GET | /api/tickets/verify/{ticket_token} | unknown/none |
| GET | /operations/status/{idempotency_key} | unknown/none |
| GET | /cancellations | unknown/none |
| GET | /cancellations/{case_reference} | unknown/none |
| POST | /internal/cancellations/{case_reference}/review | none independent (schema only) - FINDING |
| POST | /internal/cancellations/nlp-preview | none independent (schema only) - FINDING |
| GET | /internal/fraud-reviews | none independent (schema only) - FINDING |
| GET | /internal/fraud-reviews/{case_reference} | none independent (schema only) - FINDING |
| POST | /internal/fraud-reviews/{case_reference}/review | none independent (schema only) - FINDING |
| GET | /admin/trains | unknown/none |
| GET | /admin/bookings | unknown/none |
| POST | /admin/chat | none (M1 public; M4 engineer-token) |

## security (port 8004) — /docs exposed: True

| Method | Path | Auth (intended/observed) |
| --- | --- | --- |
| GET | /health | unknown/none |
| POST | /internal/fraud-score | NONE (no auth) - FINDING |
| POST | /internal/messages | agent JWT (verify_agent_token) - VERIFIED |
| POST | /internal/grounded-summary | none independent (schema only) - FINDING |
| POST | /internal/investigation-feedback | none independent (schema only) - FINDING |
| GET | /internal/investigation-feedback | none independent (schema only) - FINDING |

## m2 (port 8005) — /docs exposed: True

| Method | Path | Auth (intended/observed) |
| --- | --- | --- |
| POST | /admin/api/login | admin JWT (require_admin) - VERIFIED enforced |
| POST | /admin/api/logout | admin JWT (require_admin) - VERIFIED enforced |
| GET | /admin/api/me | admin JWT (require_admin) - VERIFIED enforced |
| GET | /admin/api/officers | admin JWT (require_admin) - VERIFIED enforced |
| POST | /admin/api/officers | admin JWT (require_admin) - VERIFIED enforced |
| GET | /admin/api/officers/audit | admin JWT (require_admin) - VERIFIED enforced |
| GET | /admin/api/officers/{officer_id} | admin JWT (require_admin) - VERIFIED enforced |
| PUT | /admin/api/officers/{officer_id} | admin JWT (require_admin) - VERIFIED enforced |
| POST | /admin/api/officers/{officer_id}/reset-password | admin JWT (require_admin) - VERIFIED enforced |
| POST | /admin/api/officers/{officer_id}/status | admin JWT (require_admin) - VERIFIED enforced |
| GET | /admin/api/roles/matrix | admin JWT (require_admin) - VERIFIED enforced |
| GET | /admin/api/health/status | admin JWT (require_admin) - VERIFIED enforced |
| GET | /admin/api/model/metrics | admin JWT (require_admin) - VERIFIED enforced |
| GET | /admin/api/model/metrics-history | admin JWT (require_admin) - VERIFIED enforced |
| GET | /admin/api/model/feature-importances | admin JWT (require_admin) - VERIFIED enforced |
| POST | /admin/api/model/retrain | admin JWT (require_admin) - VERIFIED enforced |
| GET | /admin/api/model/versions | admin JWT (require_admin) - VERIFIED enforced |
| POST | /admin/api/model/rollback/{filename} | admin JWT (require_admin) - VERIFIED enforced |
| GET | /admin/api/audit/events | admin JWT (require_admin) - VERIFIED enforced |
| GET | /admin/api/audit/summary | admin JWT (require_admin) - VERIFIED enforced |
| POST | /internal/messages | agent JWT (verify_agent_token) - VERIFIED |
| GET | /health | unknown/none |
| GET | /api/dashboard | none (public) |
| GET | /api/route-options | unknown/none |
| POST | /passenger/ask | none (public) |
| POST | /passenger/query | none (public) |
| POST | /predict-delay | unknown/none |
| GET | /route-status/{route_id} | unknown/none |
| POST | /incident-report | none (public) |
| GET | /incidents | GET public list; approve/reject require admin - VERIFIED |
| POST | /incidents/{incident_id}/approve | GET public list; approve/reject require admin - VERIFIED |
| POST | /incidents/{incident_id}/reject | GET public list; approve/reject require admin - VERIFIED |
| GET | /api/incidents/map-feed | GET public list; approve/reject require admin - VERIFIED |
| GET | /api/trains | unknown/none |
| GET | /api/stations | unknown/none |
| PATCH | /incidents/{incident_id} | GET public list; approve/reject require admin - VERIFIED |
| DELETE | /incidents/{incident_id} | GET public list; approve/reject require admin - VERIFIED |
| POST | /hub/message | JWT if secret set; M4 skips (no secret) - FINDING |
| GET | /api/ops-agent/capabilities | unknown/none |
| POST | /api/ops-agent/ask | unknown/none |
| GET | /api/ops-agent/history | unknown/none |

## m4 (port 8006) — /docs exposed: True

| Method | Path | Auth (intended/observed) |
| --- | --- | --- |
| GET | /health | unknown/none |
| GET | / | unknown/none |
| GET | /api/dashboard | none (public) |
| GET | /api/assets | unknown/none |
| POST | /asset-health | unknown/none |
| GET | /asset-status/{asset_id} | unknown/none |
| GET | /api/asset-trend/{asset_id} | unknown/none |
| GET | /api/fleet-health-summary | unknown/none |
| POST | /maintenance-report | x-engineer-token |
| PATCH | /api/reports/{report_id}/resolve | unknown/none |
| GET | /manual-search | unknown/none |
| POST | /api/engineer-login | unknown/none |
| GET | /chat-ui | none (M1 public; M4 engineer-token) |
| POST | /chat | none (M1 public; M4 engineer-token) |
| POST | /api/flag-train | x-engineer-token - VERIFIED enforced |
| DELETE | /api/flag-train/{train_id} | x-engineer-token - VERIFIED enforced |
| GET | /api/train-status/{train_id} | unknown/none |
| GET | /api/trains-under-maintenance | none (public) |
| POST | /hub/message | JWT if secret set; M4 skips (no secret) - FINDING |
| POST | /internal/messages | agent JWT (verify_agent_token) - VERIFIED |
