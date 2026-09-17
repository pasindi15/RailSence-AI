# Implementation Plan: Module 2 (Operations Agent) 100% Execution & Hub Integration

This plan details the full completion of **Module 2 (Operations & Delay-Prediction Agent / Operational Assistant)** and its integration with **Module 1 (Passenger Assistant Agent)** via **Module 3 (Central Agent Communication Hub)**.

When a passenger asks a delay/operational question in M1's chat, M1 will construct an `AgentMessage` envelope and route it through M3's Central Hub (`POST /messages`). M3 will authenticate, audit, and forward the request to M2 (`POST /internal/messages`). M2 will compute a machine learning delay prediction, retrieve historical incident precedents via RAG, generate a grounded plain-language explanation, publish alerts if applicable, and return a `delay_check_response` envelope back through M3 Hub to M1, which will render the response beneath the passenger's question in the chat interface.

---

## User Review Required

> [!IMPORTANT]
> **Port & Service Mapping**: M2 (`operations-agent`) will run on port `8005` (matching M3 Hub registry conventions). M1 runs on `8001` and M3 Hub runs on `8002`.

> [!NOTE]
> **Minimal Shared Integration Adjustments**: While M2 is the primary focus, minimal alignment in `M3` (`shared/schemas.py` intent enum) and `M1` (`hub_client.py` real POST forwarding) will be performed to allow end-to-end communication through M3 Hub.

---

## Open Questions

- None. The contracts and phase roadmaps for M1, M2, and M3 are fully defined in the repository documentation (`Operations_Roadmap.md`, `README.md`, `COMMUNICATION_CONTRACT.md`).

---

## Proposed Changes

### Component 1: Module 2 — Operations Agent Core & Internal Hub Routing (`M2-operations-agent`)

#### [MODIFY] [main.py](file:///e:/Y3%20S2/Information%20Retrieval%20and%20Web%20Analytics%20-%20IT3041/Grp%20Assignment/RailSenceAI/RailSence-AI/M2-operations-agent/main.py)
- Change default server startup port in `if __name__ == "__main__":` from `8001` to `8005` (with fallback to `os.getenv("PORT", 8005)`).
- Upgrade `receive_internal_message` (`POST /internal/messages`) and `hub_message` (`POST /hub/message`):
  - Add robust payload extraction: handle `route` and `train_id` as well as fallback parsing from `stations` array, `raw_text`, and `time` provided by M1.
  - Return response payload containing both `explanation` and `reason` (string), `similar_past_incidents` (list) and `similar_incident` (string citation), `predicted_delay_minutes`, `confidence`, `top_contributing_features`, and `model_version`.
  - Ensure all incoming Hub actions trigger audit logging and threshold alert checks (delay >= 5 min).

#### [MODIFY] [hub_client.py](file:///e:/Y3%20S2/Information%20Retrieval%20and%20Web%20Analytics%20-%20IT3041/Grp%20Assignment/RailSenceAI/RailSence-AI/M2-operations-agent/hub_client.py)
- Ensure default `HUB_BASE_URL` aligns with `http://localhost:8002` (M3 Hub default port) while respecting environment overrides.
- Provide clean async helpers for outbound delay alerts and registry heartbeats.

---

### Component 2: Module 3 — Central Communication Hub Alignment (`M3-Comunication-Hub&Booking-Agent`)

#### [MODIFY] [shared/schemas.py](file:///e:/Y3%20S2/Information%20Retrieval%20and%20Web%20Analytics%20-%20IT3041/Grp%20Assignment/RailSenceAI/RailSence-AI/M3-Comunication-Hub&Booking-Agent/shared/schemas.py)
- Expand `MemberCIntent` enum to include `delay_check`, `delay_check_response`, `delay_alert`, `issue_report`, `incident_report` so M3 Hub's Pydantic validation allows operational message envelopes from M1 to M2.

---

### Component 3: Module 1 — Passenger Assistant Hub Client Alignment (`M1-passenger_assistant`)

#### [MODIFY] [hub_client.py](file:///e:/Y3%20S2/Information%20Retrieval%20and%20Web%20Analytics%20-%20IT3041/Grp%20Assignment/RailSenceAI/RailSence-AI/M1-passenger_assistant/backend/hub_client.py)
- Update `send_to_hub` to make an actual HTTP POST call via `httpx.AsyncClient` to `HUB_BASE_URL` (`http://localhost:8002/messages`) with fallback to local mock response if M3 Hub is unreachable during offline testing.

#### [MODIFY] [main.py](file:///e:/Y3%20S2/Information%20Retrieval%20and%20Web%20Analytics%20-%20IT3041/Grp%20Assignment/RailSenceAI/RailSence-AI/M1-passenger_assistant/backend/main.py)
- Parse M3 Hub routed response (`hub_response["response"]["payload"]` or `hub_response["payload"]`) to build the passenger reply with delay prediction, explanation/reason, and historical incident citation.

---

### Component 4: M2 Operations Model Training, NLP & Evaluation Verification

- Ensure `ml/train_delay_model.py` is executed to generate fresh `delay_model.pkl` and `feature_importances.json`.
- Ensure `nlp/evaluate_nlp.py` and `evaluation/rag/evaluate_retrieval.py` are executed to ensure committed evaluation artifacts (`delay_model_metrics.json`, `classification_metrics.json`) are updated.

---

## Verification Plan

### Automated Tests
1. **M2 Standalone Unit & API Tests**:
   - Run python endpoint checks against M2 (`POST /predict-delay`, `GET /health`, `POST /incident-report`, `GET /api/dashboard`).
2. **M3 Hub Routing Test**:
   - POST `AgentMessage` envelope (`intent="delay_check"`, `receiver_agent="operations-agent"`) to M3 Hub `http://localhost:8002/messages`.
   - Verify M3 Hub validates, audits, and routes to M2 on port 8005, returning 200 OK with `status: "routed"` and M2's `delay_check_response` payload.
3. **M1 Passenger Assistant Integration Test**:
   - POST user question `"Is the 14:35 train from Colombo Fort to Kandy delayed?"` to M1 `http://localhost:8001/chat`.
   - Verify reply contains delay prediction minutes, grounded reason/explanation, and historical precedent citation via M3 Hub -> M2.

### Manual Verification
1. Launch M3 Hub (port 8002), M2 Operations Agent (port 8005), and M1 Passenger Assistant (port 8001).
2. Open M1 Chat frontend, ask operational delay question.
3. Inspect live chat response under the question, verify M2 Operations Dashboard updates live with the audited query and delay alert event.
