IT3041 · INFORMATION RETRIEVAL & WEB ANALYTICS
RailSense AI
Complete Implementation Guide — Agentic AI System for Railway Operations
🧑‍💼 Passenger Assistant 🚦 Operations & Delay Prediction 🛡️ Security & Fraud 🔧 Maintenance Intelligence
Domain: Railway | Group size: 4 members | Architecture: 4 cooperating agents + shared MCP-style Hub
Design language: Light theme, glassmorphism-influenced, high-contrast accent colors per agent
Purpose of this document: A step-by-step build guide — exactly what each member implements, how their part connects to the others, and what each member presents at Mid-Evaluation and Viva.
1. Executive Summary
RailSense AI is a multi-agent platform built around four cooperating, specialized agents — a Passenger Assistant, an Operations & Delay-Prediction agent, a Security & Fraud agent, and a Maintenance & Asset Intelligence agent — all coordinated through a central Agent Communication Hub that speaks a lightweight MCP-style JSON protocol.

Each agent is a genuinely independent service (its own FastAPI backend, its own LLM prompt design, its own NLP pipeline, its own retrieval corpus, and its own light-themed dashboard) that becomes useful on its own but becomes powerful together — e.g. a passenger asking "is my train delayed?" triggers a live call from the Passenger Agent to the Operations Agent through the Hub, and the Operations Agent's prediction is cross-checked against the Maintenance Agent's equipment-health data before being returned.

Why this architecture wins on the rubric: it visibly exceeds "at least two agents," gives every required component (LLM, NLP, IR, Security, Communication Protocol) genuine depth on each member's slice, and produces a commercialization story that reads like a real product suite rather than a single demo chatbot.
1.1 Architecture at a glance
HUB Central FastAPI service. Verifies every message's auth token, routes JSON messages between agents, and publishes/subscribes agents to system-wide events (delay alerts, maintenance alerts, fraud flags).
PASSENGER Chat interface (web) → NLU (intent + NER) → RAG over FAQs/schedules → calls Hub for live data → LLM composes final grounded reply.
OPERATIONS Delay-prediction ML model + incident-log summarizer → serves predictions to Passenger Agent → publishes delay_alert events.
SECURITY Owns the Hub's auth layer, encrypts sensitive fields, screens ticket transactions for fraud, and reviews the whole system's input-sanitization posture.
MAINTENANCE Predictive maintenance from sensor/log data + RAG over equipment manuals → publishes maintenance_alert events consumed by Operations.
1.2 What "done" looks like by Week 10
Component	Minimum bar	Stretch (for top marks)
Agents	2 agents exchanging one message type	4 agents, 6+ message types, event-driven (pub/sub) not just request/response
LLM	Single prompt call	Structured prompts w/ function-calling, grounded via RAG, multilingual
NLP	One NER or summarization call	NER + summarization + classification, evaluated with real metrics
IR	Keyword search	Embedding-based RAG with citation of retrieved source
Security	Hardcoded API key	JWT auth, input sanitization, encryption in transit & at rest, audit logging
UI	Basic form	Polished light-theme dashboards per agent, live demoable
2. UI/UX Design System — "Light Rail" Theme
Every screen across all four agents shares one design system so the final product looks like a single cohesive company product, not four separate student projects glued together. Each agent gets its own accent color for quick visual identity, on a shared light, airy base.

2.1 Color tokens
Token	Hex	Usage
Background	#F7F9FC	App background — soft off-white, never pure white (reduces glare, feels premium)
Surface	#FFFFFF	Cards, panels, modals
Brand / Primary	#4F46E5	Nav bar, primary buttons, active states, the RailSense logo
Passenger accent	#0EA5E9	Passenger Assistant chat bubbles, links, highlights
Operations accent	#F59E0B	Ops dashboard charts, delay badges
Security accent	#F43F5E	Alerts, fraud flags, destructive actions
Maintenance accent	#8B5CF6	Asset-health cards, maintenance calendar
Text / Ink	#1E293B	Body text
Muted text	#64748B	Captions, timestamps, secondary labels
2.2 Typography & components
Font pairing: a rounded geometric sans (e.g. "Poppins" or "Plus Jakarta Sans") for headings, and "Inter" or system sans for body text — gives a modern, friendly, advanced feel without looking playful/childish.
Cards: 12–16px border radius, soft shadow (0 4px 16px rgba(15,23,42,0.06)), 1px hairline border in a very light gray — this is what gives the "glassmorphism-lite" premium look while staying readable and light-themed (avoid heavy blur/dark glass — keep it light and crisp).
Buttons: filled primary (brand color, white text, 10px radius), ghost/secondary (brand-colored outline), all with a subtle hover-lift shadow.
Status badges: pill-shaped, colored background at 15% opacity of the accent color with full-opacity text — e.g. a delay badge is light-amber background with dark-amber text.
Charts: soft gradient fills under line charts, rounded bar tops, never harsh pure-red/green — use the accent palette consistently.
Motion (if using React): gentle fade/slide-in on card load (150–250ms), a subtle pulsing dot for "live" data, typing-indicator dots in the chat.
2.3 Screen mockups (representative)
🧑‍💼 Passenger Assistant — Chat
Hi! I can help with schedules, tickets, or delays. Ask me in Sinhala, Tamil, or English 🙂
Colombo to Kandy මාර්ගයේ ඊළඟ දුම්රිය කීයටද?
The next Colombo → Kandy train departs 14:35 (Podi Menike). Live status: on time. Source: schedule DB + Operations Agent.
🚦 Operations Dashboard
Active trains
34
 Avg delay today
6.2 min
 Predicted risk (PM peak)
Medium
Route heatmap · Incident feed (auto-summarized) · Model confidence indicator

🛡️ Security Console
Sessions today
1,204
 Flagged transactions
3
 Avg risk score
Low
Flagged-transaction table with plain-language "why flagged" explanation · Full audit trail viewer

🔧 Maintenance Console
Assets tracked
58
 Due for service
4
 Manual search
Asset health cards (green/amber/red) · Maintenance calendar · "Ask the manual" search bar (RAG)

Build these four screens as one shared React/Next.js app with agent-scoped routes (/passenger, /ops, /security, /maintenance) sharing a component library — this alone visibly signals "advanced, cohesive product" to evaluators within the first 10 seconds of the demo.

3. Member A — Passenger Assistant Agent
Owns: conversational LLM · multilingual NLP · RAG over policy/schedule docs · passenger-facing chat UI
3.1 Exact tasks
Service scaffold: create passenger-agent/ FastAPI service with endpoints POST /chat, POST /feedback, GET /health.
Intent & entity extraction (NLP): use spaCy (custom NER model or rule-based patterns) or an LLM function-call to extract: intent (schedule_query, delay_check, complaint, fare_query), station names, dates/times, and language. This is your required NER component.
Language handling: detect Sinhala / Tamil / English (langdetect or a small classifier) and route to the right response language — this is your strongest Responsible AI / fairness demo.
Retrieval (IR): chunk and embed the railway FAQ, fare policy, and static schedule documents into ChromaDB using sentence-transformers; on each query, embed the user's question, retrieve top-k chunks, and pass them into the LLM prompt as grounding context (classic RAG).
LLM response composition: system prompt instructs the model to answer only from retrieved context + any live data returned by other agents, and to say "I'm not sure" rather than hallucinate — cite which source/agent the answer came from.
Live data via the Hub: when intent = delay_check, build a Hub message and call the Operations Agent; when intent = complaint about a physical issue (e.g. broken AC), forward a structured ticket to the Maintenance Agent via the Hub.
Security on your endpoint: validate/sanitize all incoming chat text with Pydantic models (reject script tags, excessive length, control characters) before it ever reaches the LLM prompt (prevents prompt injection from becoming a system-wide issue).
Frontend: build the chat UI per the Section 2 design system — chat bubbles, quick-reply buttons ("Check delay", "Report an issue", "View schedule"), typing indicator, and a small "sources" footnote under grounded answers.
Evaluation: write 15–20 test conversations covering all 3 languages and all 4 intents; report NER accuracy and RAG retrieval relevance informally (precision@3 on a handful of manually-checked queries).
3.2 Folder structure
passenger-agent/
├── main.py                # FastAPI app, /chat /feedback /health
├── nlu/
│   ├── intent_classifier.py
│   ├── ner_extractor.py
│   └── lang_detect.py
├── rag/
│   ├── embed_documents.py # one-time: builds the Chroma index
│   └── retriever.py
├── hub_client.py          # sends/receives Hub messages
├── prompts/
│   └── system_prompt.md
├── data/faq_docs/         # source policy & schedule text files
└── frontend/ (Next.js chat widget)
3.3 What Member A presents
Live multilingual chat demo (Sinhala, Tamil, English) with a grounded, cited answer.
A live "delay_check" round trip: show the exact JSON message sent to the Hub and the Operations Agent's reply, then the natural-language answer the user sees.
One deliberately malicious/nonsense input, showing it gets sanitized/rejected gracefully.
Owns editing + narration of the Gen AI explainer video (final submission).
4. Member B — Operations & Delay-Prediction Agent
Owns: delay-prediction ML/LLM · incident summarization · operations dashboard
4.1 Exact tasks
Service scaffold: operations-agent/ FastAPI with POST /predict-delay, GET /route-status/{route_id}, POST /incident-report.
Dataset: build (or source) a synthetic historical dataset: route, station, scheduled time, actual time, weather, day-type, incident-type, delay-minutes. This single dataset unblocks your ML model and your IR corpus.
Delay-prediction model: train a scikit-learn regressor (RandomForest or GradientBoosting) on route/time/weather features to predict expected delay in minutes. Log feature importances — this feeds your explainability story.
LLM explanation layer: take the model's numeric prediction + the top contributing features and have the LLM turn it into a plain-language explanation ("expect ~9 min delay — historically this route sees congestion at this hour and light rain is forecast").
NLP — summarization & classification: when a raw incident report comes in (free text from staff), use an LLM or a Hugging Face summarization pipeline to produce a 1–2 sentence operator brief, and classify the incident type (signal fault / weather / mechanical / other).
Retrieval (IR): embed past incident descriptions; when a new delay is predicted, retrieve the 2–3 most similar historical incidents to show "this has happened before, here's what happened" — a strong, demoable IR use case.
Hub interactions: respond to delay_check requests from the Passenger Agent; publish a delay_alert event whenever predicted delay exceeds a threshold, which the Security Agent and Maintenance Agent both subscribe to.
Security on your endpoint: sanitize incident-report free text, rate-limit the prediction endpoint, log every prediction request for audit.
Dashboard: per Section 2 — live route status, delay heatmap, model confidence, auto-summarized incident feed.
4.2 Folder structure
operations-agent/
├── main.py
├── ml/
│   ├── train_delay_model.py
│   ├── delay_model.pkl
│   └── predict.py
├── nlp/
│   ├── summarize_incident.py
│   └── classify_incident.py
├── rag/incident_retriever.py
├── hub_client.py
└── frontend/ (ops dashboard)
4.3 What Member B presents
Leads the Mid-Evaluation demo (Week 6): system architecture walkthrough, agent roles, live progress demo, Responsible AI check-in, brief commercialization pitch.
Live delay prediction with the plain-language explanation and a similar-past-incident citation.
Model metrics (MAE/RMSE) and a short note on where the model is weakest (honesty here reads well in a viva).
5. Member C — Security & Fraud Agent (+ Hub Owner)
Owns: the Agent Hub, authentication, encryption, fraud/anomaly detection, system-wide security review
5.1 Exact tasks
Build the Hub: agent-hub/ — the central FastAPI service every other agent talks through. Define the message envelope (see Section 6.2), a service registry (which agents are online), and a routing function that forwards a message to the correct agent's endpoint.
Authentication: issue short-lived JWTs for passenger chat sessions and for inter-agent calls; every message entering the Hub must carry a valid token, or it's rejected. Staff-facing dashboards use bcrypt-hashed password login.
Encryption: enforce HTTPS/TLS between all services (self-signed cert is fine for the demo — explain the production TLS setup in the report); encrypt PII fields (phone numbers, NIC numbers if used) at rest using AES via a small crypto utility library.
Fraud / anomaly detection: on a synthetic ticket-booking dataset, implement an Isolation Forest (or a clear rule-based baseline: same card used across improbable travel times/locations, rapid repeated bookings) to flag suspicious transactions.
NLP: classify free-text complaint/transaction-dispute descriptions for fraud-relevant keywords/patterns (a simple text classifier or LLM zero-shot classification).
LLM explanation: for every flagged transaction, generate a short plain-language reason a human analyst can quickly read ("flagged: 4 bookings in 3 minutes from different stations").
Retrieval (IR): embed past (synthetic) fraud case write-ups; retrieve similar historical cases for any new flag, to support the analyst's decision.
System-wide security review (cross-cutting): write and run a short checklist against all four agents — input sanitization present? rate limiting present? secrets in .env, not hardcoded? dependencies free of known critical CVEs (pip-audit / npm audit)? Document findings — this becomes part of your Responsible AI / data-protection report section.
Dashboard: Security console per Section 2 — flagged transactions, plain-language "why flagged," full audit-trail viewer.
5.2 Folder structure
agent-hub/
├── main.py            # routing, service registry
├── auth/
│   ├── jwt_utils.py
│   └── password_utils.py
├── schema.py           # the shared message envelope (Pydantic model)
└── audit_log.py

security-agent/
├── main.py             # /auth/login /auth/verify /fraud/check /audit-log
├── fraud/
│   ├── train_isolation_forest.py
│   └── score_transaction.py
├── nlp/classify_dispute_text.py
├── rag/fraud_case_retriever.py
├── crypto/aes_utils.py
└── frontend/ (security console)
5.3 What Member C presents
Live demo: a malicious/injection input being blocked at the Hub, and an encrypted PII field shown as unreadable ciphertext in the DB vs. the decrypted view in the dashboard.
A live fraud flag with its plain-language explanation and a retrieved similar past case.
Explains the Hub's routing live — send one message on screen, show it arrive at the receiving agent.
Leads the Responsible AI report section, compiling each member's fairness/explainability/data-protection notes into one coherent write-up.
6. Member D — Maintenance & Asset Intelligence Agent (+ Integration Lead)
Owns: predictive maintenance · RAG over manuals · Docker/repo integration · report compilation
6.1 Exact tasks
Service scaffold: maintenance-agent/ with POST /log-ingest, GET /maintenance-status/{train_id}, POST /manual-query.
Dataset: synthetic sensor/maintenance-log dataset — train ID, component, sensor readings over time, technician free-text notes, last-service date.
Predictive maintenance model: a simple trend/threshold model or lightweight regression estimating "time to next required service" or a red/amber/green health flag per component.
NLP: NER on technician notes (extract component names, dates, part numbers) and summarization of long maintenance logs into a short status brief.
LLM report generation: combine the structured prediction + retrieved manual excerpts into a natural-language maintenance recommendation ("Component X shows early wear signs consistent with manual section 4.2 — recommend inspection within 2 weeks").
Retrieval (IR): chunk and embed equipment manuals/spec sheets (PDF → text → embeddings); this is your RAG use case — answers must be grounded in the actual manual text, not invented.
Hub interactions: subscribe to delay_alert events from Operations (to check "did equipment condition contribute to this delay?"); publish maintenance_alert events that Operations subscribes to (so upcoming maintenance can influence scheduling).
Security on your endpoint: validate sensor-log ingestion payloads (type/range checks), sanitize technician free-text before NER/summarization.
Integration & delivery (cross-cutting): own the top-level docker-compose.yml that brings up all 4 agents + the Hub together; own the GitHub repo structure and top-level README; compile the Final Report from each member's section into the provided template.
6.2 Folder structure
maintenance-agent/
├── main.py
├── predictive/
│   ├── health_model.py
│   └── predict_status.py
├── nlp/
│   ├── extract_entities.py
│   └── summarize_log.py
├── rag/
│   ├── embed_manuals.py
│   └── manual_retriever.py
├── hub_client.py
└── frontend/ (maintenance console)

/ (repo root, Member D owns)
├── docker-compose.yml     # brings up hub + all 4 agents + frontends
├── README.md
└── /report/ (final report source, compiled from all members)
6.3 What Member D presents
Live predictive maintenance demo: ingest a log, show the health flag and the LLM-generated recommendation citing the manual.
A live "ask the manual" RAG query with the retrieved source passage shown alongside the answer.
A full-system docker-compose up demo — bring up all four agents + Hub in one command, proving genuine integration, not four disconnected demos.
Walks the GitHub repo structure live during the viva.
7. How the Four Parts Connect — Message Flow & Relationships
This is the section to rehearse together before Week 9 integration — it is also exactly what evaluators probe hardest, since it proves the system is genuinely agentic (agents making autonomous calls to each other) rather than four separate apps.

7.1 Relationship map
From	To	Message / Event	Why
Passenger	Operations	delay_check (request/response)	Passenger asks about a specific train; Operations returns live prediction + explanation.
Passenger	Maintenance	issue_report (request)	Passenger reports a physical problem (e.g. broken AC); forwarded as a maintenance ticket.
Operations	Security, Maintenance	delay_alert (published event)	Broadcast when predicted delay crosses a threshold; Security correlates for anomalies, Maintenance checks for equipment causes.
Maintenance	Operations	maintenance_alert (published event)	Upcoming/urgent maintenance may require schedule adjustment.
Security	All agents	auth_token verify (middleware, every call)	Every inter-agent message passes through Hub auth verification owned by Security.
All agents	Hub	register / heartbeat	Service discovery — Hub knows which agents are online and where to route messages.
7.2 Shared message envelope (agree on this in Week 3)
{
  "message_id": "b7e1-...-uuid",
  "sender_agent": "passenger-agent",
  "receiver_agent": "operations-agent",
  "intent": "delay_check",
  "payload": {
    "route": "Colombo Fort - Kandy",
    "train_id": "PM-4082",
    "requested_time": "2026-09-10T14:35:00+05:30"
  },
  "auth_token": "eyJhbGciOi...",
  "timestamp": "2026-09-10T13:58:12+05:30"
}
7.3 A full worked example (walk through this live in the demo)
1. Passenger types: "Is the 14:35 Colombo–Kandy train delayed?" → Passenger Agent runs NER, extracts route + time, classifies intent as delay_check.
2. Passenger Agent builds a Hub message (schema above) and sends it → Hub verifies auth token → routes to Operations Agent.
3. Operations Agent runs its model, retrieves 2 similar past incidents, asks the LLM to compose a plain-language explanation → sends the response back through the Hub.
4. Because predicted delay is 9 minutes (above the 5-minute alert threshold), Operations Agent also publishes a delay_alert event.
5. Maintenance Agent, subscribed to delay_alert, checks whether the affected train has any open maintenance flags — none found, so no correlation noted.
6. Passenger Agent receives the Operations response and composes the final natural-language reply, citing that the answer is live (not static schedule data).
8. Responsible AI & Security — Implementation Checklist
8.1 Responsible AI (map each item to who implements it)
Principle	How it's implemented	Owner
Fairness	Chat tested equally across Sinhala, Tamil, English; report any accuracy gap found	Member A
Explainability	Every prediction/flag ships with a plain-language "why," not just a score	Members B & C
Transparency	Chat UI discloses it's an AI assistant; flagged fraud cases are escalatable to a human	Member A & C
Data protection	PII encrypted at rest, minimal retention window stated in report, access logging	Member C
Bias check	Disclose if the synthetic delay dataset under-represents certain routes/regions	Member B
8.2 Security implementation checklist
☐ JWT auth on every agent-to-agent and passenger-to-agent call
☐ Input sanitization / Pydantic validation on every public endpoint (all 4 agents)
☐ Rate limiting on chat, prediction, and fraud-check endpoints
☐ TLS between services (self-signed for demo, noted as production gap)
☐ AES encryption of PII fields at rest
☐ Centralized audit log of every Hub-routed message (who, when, what intent)
☐ Secrets management via .env / not committed to GitHub
☐ Dependency vulnerability scan (pip-audit, npm audit) run before final submission
9. Commercialization Plan
Element	Detail
Product	RailSense AI — B2G SaaS suite, white-labelable, licensed to national/regional railway authorities
Pricing — Starter	Passenger chatbot + basic delay prediction, single route/region, low monthly fee per station
Pricing — Operations	Adds ops dashboard + maintenance agent, mid-tier per-station pricing
Pricing — Enterprise	Full 4-agent suite + custom integrations + SLA support, annual contract, custom quote
Target users	Railway authorities (e.g. Sri Lanka Railways), transport ministries, later: bus/metro authorities, private freight rail
Deployment	Cloud multi-tenant SaaS, with an on-prem option for data-residency-sensitive government contracts
Go-to-market	Pilot on one region/route, gather usage & accuracy data, use it to expand the contract
10. Week-by-Week Timeline
Week	Milestone	Everyone does
1	Group registration + topic selected: Railway	Confirm roles from Section 3–6
2	Domain brief & report template released	Build the shared synthetic dataset — unblocks all 4 agents
3	Assignment officially begins	Agree on the Hub message schema (Section 7.2); scaffold each service
4	Build sprint 1	Each agent's LLM call working end-to-end
5	Build sprint 2	Each agent's NLP component (NER/summarization/classification) working
6	Mid Evaluation (20 marks)	Architecture, roles, comms flow, live demo, RAI check, brief commercialization pitch (Member B leads)
7	Post-feedback sprint	Each agent's IR/RAG component working
8	Security hardening	Member C leads: auth, sanitization audit, encryption across all agents
9	Full integration week	All 4 agents talking through the Hub end-to-end; UI polish per Section 2
10	Final Submissions	Gen AI video (Member A), Final report (Member D compiles), GitHub repo polish
11	Viva	Each member defends their own agent + understands the whole system
11. Presentation & Viva Guide — What Each Member Must Be Ready to Show
Member	Mid-Eval contribution	Final video/report role	Viva — must independently explain
A — Passenger	Live multilingual chat demo	Leads & edits the Gen AI video	NLU pipeline, RAG grounding, one full Hub round-trip, input sanitization
B — Operations	Leads the mid-eval deck & demo script	Writes the model & evaluation section of the report	Model training/metrics, incident summarization, delay_alert publishing
C — Security	Demos Hub routing + auth	Leads the Responsible AI report section	Hub architecture, JWT/auth flow, encryption, fraud model, security checklist findings
D — Maintenance	Demos predictive maintenance	Compiles final report + owns GitHub/Docker	RAG-over-manuals, docker-compose integration, repo structure, maintenance_alert flow
Rehearse Section 7.3's worked example together as a group at least once before Mid-Eval and once before the Viva — being able to trace one request across all four services live is the single highest-impact thing you can demo.
RailSense AI — IT3041 Group Implementation Guide · Generated as a working reference document for team planning