# RailSense AI: Viva Ready Guide (Detailed Version)

This guide explains the whole project in plain language, with enough detail to answer follow-up
questions. Each section starts with a **simple answer** (what to say first) and then gives **more
detail** (what to say if the examiner asks "how?" or "why?").

Numbers come from the committed evaluation files (`prep.md` lists the source file for each one).

**Reading order if you are short of time:** Sections 0, 1, 4, 6, 8, 11, 13, 14 and the Q&A in 24.

---

## Table of contents

0. The 30-second pitch
1. Team and responsibilities
2. Problem, target audience and customers
3. Big picture architecture
4. M2 full flow: from the user's question to the answer
5. How the other three agents work
6. How the ML model works and connects to M2
7. NLP in M2 (how the system "understands" text)
8. Why IR, how it works, and where it is used
9. Why we use four LLMs
10. LLM and running costs: what we have to pay
11. Commercialisation plan
12. Responsible AI
13. System-side fairness: what fairness users get
14. Data privacy, data leakage and protecting sensitive data
15. How to identify whether a record comes from the system or not
16. Security: roles, tokens and the Hub
17. Assignment requirement checklist
18. Evaluation results explained
19. Resilience: what happens when something fails
20. Pros and cons
21. Challenges we faced and how we solved them
22. Future work
23. Tech stack
24. Likely viva questions with full answers
25. Demo order
26. Key terms glossary

---

## 0. The 30-second pitch (memorise this)

> "RailSense AI is a multi-agent railway intelligence platform for Sri Lanka Railways. Four AI
> agents work together. **M1** talks to passengers in English, Sinhala (including Singlish) and
> Tamil. **M2** predicts train delays, tracks trains live, handles incident reports and gives
> officers a control room. **M3** is the communication hub that securely connects all agents, plus
> the booking system and a fraud detector. **M4** monitors train health and maintenance.
>
> Our main design rule is: **facts come from data, ML models and databases; the LLM only puts
> those facts into words.** If the LLM writes any number that isn't in the real data, we throw its
> answer away and show a safe template answer instead."

**If they ask "what makes it different?":**
- Most chatbots just send the question to an LLM. Ours first gets the facts (ML prediction,
  database records, retrieved documents), then uses the LLM only to phrase them, and checks it.
- Four agents share one train registry and one secure message system, so they work as one product.
- It still works when the LLM or the cloud database is down, because every part has a fallback.

---

## 1. Team and responsibilities

| Module | What it does | Member |
| --- | --- | --- |
| **M1** Passenger Assistant | Multilingual chat (English, Sinhala, romanized Sinhala "Singlish", Tamil), intent + entity detection, FAQ RAG, passenger login, chat history, "Choo" floating assistant | **Thisarani Kawya** |
| **M2** Operations & Delay Prediction | Delay ML model, live train tracking, passenger operations answers, incident NLP + RAG, verified incident map, Control Room, Admin Console with RBAC, Operations Assistant (LLM) | **Pasindi Alawatta (team leader)** |
| **M3** Hub, Booking & Security | Communication Hub (JWT-signed messages, allowlist, audit), booking with QR tickets, cancellations, fraud detection (IsolationForest) | **Navoda Dasun** |
| **M4** Maintenance & Asset Intelligence | Asset health ML, technician-note NLP, maintenance manual RAG, train out-of-service flags, engineer assistant (LLM) | **Primesh Marasingha** |

**Pasindi's two roles:**
1. **M2 owner:** everything in `M2-operations-agent/`.
2. **Team leader:** integration of all four modules, the shared train registry (one list of trains
   for everyone), the one-command launcher `start.py`, the unified gateway (`frontend/serve.py`),
   the final report fact base (`prep.md`) and the commercialisation page (`/admin/commercial`).

---

## 2. Problem, target audience and customers

### 2.1 The problem
- Passengers can't easily find out **whether their train is late, why, and when it will arrive**.
- Information is often only in one language, and many people **can't type in Sinhala script**.
- Staff use **separate tools** for operations, booking, fraud and maintenance that don't talk to
  each other. For example, a train under repair can still be booked.
- Incident information is either hidden or released without checking.

### 2.2 Target audience (who uses it)

| User | Their need | What RailSense gives them |
| --- | --- | --- |
| **Passengers** (public, commuters, tourists, people without a Sinhala keyboard) | "Is my train late? When will it reach my station? Can I book?" | Chat in their own language, live train board, Delay popup, booking with QR ticket, verified incident map |
| **Operations engineers / control-room officers** | See network status, predict delays, ask quick questions | Control Room dashboard, delay prediction lab, Operations Assistant |
| **Administrators** | Control what the public sees, manage staff and the ML model | Approve/reject incidents, officers and roles, retrain/rollback model, audit log |
| **Security / booking reviewers** | Stop fraud fairly | Fraud review queue, cancellation review |
| **Maintenance engineers** | Know which trains are unsafe | Asset health scores, maintenance flags, manual search, engineer chat |

### 2.3 Customers (who pays)
1. **Primary:** Sri Lanka Railways (Department of Railways), its stations and control rooms.
2. **Secondary:** regional rail, metro and bus authorities. The same agents work for any scheduled
   network; timetables, manuals and policies are just loaded as data.
3. **Extension:** private, tourist and freight rail operators (lighter deployments).

---

## 3. Big picture architecture

```
Passenger browser (port 3000)              Officer browser (port 3001)
            \                                     /
             \------- Unified Gateway -----------/      frontend/serve.py
                 |           |            |
                M1          M2           M4              via /svc/m1, /svc/m2, /svc/m4
                 \           |            /
                  \---- M3 Communication Hub ----\       JWT-signed AgentMessage, allowlist, audit
                            |               |
                      M3 Booking      Security & Fraud agent
                            |
         Supabase PostgreSQL + pgvector  (shared database + shared train registry)
         Upstash Redis                   (delay_alert and maintenance_alert events)
```

**Explaining each piece:**

- **Gateway (`frontend/serve.py`):** the single "front door". Browsers only talk to two ports:
  **3000 for passengers** and **3001 for officers**. The gateway forwards requests to the right
  agent. Pages never hard-code an agent's port. The gateway also **signs Hub messages on the
  server**, so the secret key never reaches the browser.
- **Agents (internal ports):** M1 8001, Hub 8002, Booking 8003, Security 8004, M2 8005, M4 8006.
  Each is a separate FastAPI service, so one can fail without bringing down the others.
- **Hub (M3):** the "post office" between agents. Every agent-to-agent message goes through it, is
  checked, and is logged.
- **Supabase:** cloud PostgreSQL database with **pgvector** (an extension that stores embeddings and
  does similarity search). The `trains` table is the **single source of truth** for train IDs.
- **Upstash Redis:** a fast message channel. M2 publishes `delay_alert`, M4 publishes
  `maintenance_alert`, so other systems can subscribe later (e.g. SMS alerts).
- **`start.py`:** one command starts everything. It picks free ports (moves to the next free one if
  a port is busy), starts 6 agents + 2 gateway sides, health-checks each one and prints the two URLs.

**Agent protocol:** our own **JWT-signed `AgentMessage` envelope (schema v1.1) over HTTP/JSON**.
Each message has `message_id`, `sender_agent`, `receiver_agent`, `intent` (e.g. `delay_check`),
`payload`, `auth_token`, `timestamp`, `correlation_id` and `hop_count`. Call it
"**MCP-inspired**", not real MCP.

---

## 4. M2 full flow: from the user's question to the answer

M2 receives questions from **four different places**. You should be able to explain all four.

### 4.1 Passenger asks in the M1 chat

**Example:** *"Any train to Polonnaruwa after 19:15?"* or *"Where is the Night Mail now?"*

**Step 1: M1 receives the message.**
M1 detects the **language** (Sinhala/Tamil letters, the Singlish word list, or `langdetect`), checks
whether it is just a greeting, finds the **intent** (what the user wants) and runs **NER** to pull out
stations, train, date and time.

**Step 2: M1 decides who should answer.**
If the question is in **English** and the intent is an operations one (`delay_check`,
`train_status`, `train_info`, `schedule_query` or `unknown`), M1 sends it to M2 at
`POST /passenger/query`. Fares, policies and booking stay with M1.

**Step 3: M2 understands the question (NLP, `nlp/passenger_query.py`).**
- **Intent:** keyword rules first ("where", "late", "delay", "after", "reach"…). If the words are
  misspelt ("wher is it", "dealyed?"), a **TF-IDF character n-gram classifier** trained on example
  questions still finds the right intent.
- **Entities (NER):** stations (and whether each one is the origin or destination), train ID, train
  number, train name ("Night Mail", "Podi Menike"), time ("after 19:15") and date. Station names use
  **fuzzy matching**, so "Polonaruwa" still matches "Polonnaruwa".

**Step 4: M2 gets the facts from real data (no LLM here).**
- **Live train board** for today's services.
- **Live tracker (`live_tracker.py`):** builds a station-by-station timetable and works out where the
  train is right now on the **Asia/Colombo clock**. Intermediate station times are shared out by
  track distance. Overnight trains are handled: a 19:15 → 04:30 train is "not yet departed" at 18:52.
- **Verified incidents** on the map that are on the train's path add delay to every later stop.
- **Delay:** from the train's real recorded journeys, otherwise from the ML model.

**Step 5: M2 writes the answer (template NLG).**
Code builds a friendly sentence from the facts, e.g. *"The Night Mail is between Kurunegala and
Maho, about 6 minutes late. Expected at Anuradhapura around 23:42."* Every number comes from the data.

**Step 6: back to M1, then to the passenger.**
If M2 can't answer (or declines), M1 answers with its own FAQ RAG and LLM.

> The same delay question can also travel **M1 → Hub → M2** as a signed `delay_check` message.
> M2 answers with a `delay_check_response` message back through the Hub.

### 4.2 Passenger clicks "Delay" or "Operations" on the live train board

Each train on the passenger home page has **Delay** and **Operations** buttons. They open an
animated popup that calls `POST /passenger/ask` with the question and the clicked train's details.

| Step | What happens | Example |
| --- | --- | --- |
| 1. Intent detection | One of: delay, ETA, departure, location, reason, maintenance, incidents, stops, greeting, status, or **handoff** | "When will it reach Kandy?" → ETA, station = Kandy |
| 2. Live journey | `live_tracker.compute_live()` finds the train's current position and the time at every stop | "Between Rambukkana and Kadugannawa" |
| 3. Map disruptions | A verified incident on the route delays every later stop. The size of the delay = **median delay of the most similar past incidents** found by IR | Signal fault at Polgahawela → +7 min after Polgahawela |
| 4. Evidence | Recorded journeys or the ML model; for "why" questions, retrieved similar incidents | "Similar heavy-rain incidents on this line caused 6–9 min delays" |
| 5. NLG | Code builds the reply, a delay gauge and follow-up suggestions | "Instead of the scheduled 08:35, expect it at Kandy around 08:42" |
| 6. Handoff | Booking, fare and refund questions are sent to M1 | "How much is a ticket?" → M1 |

### 4.3 Delay prediction: where the ML model connects

This runs when an officer uses the prediction screen, when the Ops Assistant calls `predict_delay`,
or when a Hub `delay_check` arrives.

```
Input: route, train, station, scheduled hour, weather, day type, incident type
  │
  1. Check the train exists in the shared Supabase "trains" table (unknown → rejected)
  2. Exact historical lookup: was this train/route actually recorded?
        yes → use the real record                               → confidence HIGH
  3. Otherwise → ML model (GradientBoostingRegressor) predicts minutes
                                                                 → confidence MEDIUM
                                    (LOW if prediction ≥ 20 min or fewer than 10 similar samples)
  4. IR: retrieve the top-3 similar past incidents (pgvector, or TF-IDF offline)
  5. Explanation = prediction + top feature importances + retrieved incidents
  6. If delay ≥ 5 minutes → publish "delay_alert" to the Hub and Upstash Redis
  7. Write an audit event
  │
Output: predicted_delay_minutes, confidence, explanation, similar_past_incidents, model_version
```

**Why "exact history first"?** A real recorded observation is better evidence than a prediction.
The model is used only when there is no real record.

**Example explanation:** *"Predicted delay 16.2 min (medium confidence). Main factors: heavy rain and
the Kandy route. Similar past incidents: track-bed flooding near Kandy (18 min), heavy rain at
Peradeniya (14 min)."*

### 4.4 Officer asks the Operations Assistant (the LLM part of M2)

**Example:** *"Which route has the worst delays right now?"*

```
Officer logs in → bcrypt password check → signed JWT with their role
  │
  ▼
Question → Gemini, given ONLY the tools this role is allowed (function calling)
  │
  ├── Gemini chooses a data tool, e.g. get_route_status
  │      → backend runs the tool on real data → JSON result
  │      → Gemini writes a sentence from that JSON
  │      → NUMBER GUARD: every number in the sentence must appear in the tool results
  │           fail → LLM text discarded → code-built template answer shown instead
  │
  └── Gemini chooses a "signal" tool → fixed, pre-written message:
         report_restricted (🔒 admin only) / report_insufficient / report_out_of_scope
  │
  ▼
Answer + sources (citations) + stat chips + technique badges (LLM · NLP · IR · RAG · ML …)
Saved to this officer's private history + audit log
```

**The 7 tools:**

| Tool | What it returns | Admin | Ops Engineer |
| --- | --- | --- | --- |
| `get_dashboard_kpis` | Network delay, on-time %, trips | ✔ | ✔ |
| `get_route_status` | One corridor's status and incidents | ✔ | ✔ |
| `predict_delay` | Same as `/predict-delay` (no alert sent) | ✔ | ✔ |
| `get_incident_queue` | Incidents (rejected ones never returned) | ✔ | ✔ |
| `get_model_metrics` | MAE, R², feature importances | ✔ | 🔒 |
| `get_audit_log` | Audit events | ✔ | 🔒 |
| `check_system_health` | Supabase / Hub / Upstash status | ✔ | 🔒 |

**Extra safeguards:**
- Text the LLM writes **without calling any tool is never shown**.
- Citations and stat chips are generated by **code**, not by the LLM.
- At most **4 tool rounds** and a **25-second timeout** per question (controls cost and waiting).
- **No Gemini key, or Gemini fails** → a keyword router picks the same tools with the same role
  rules, so behaviour is the same, just with template wording.
- Each reply has an `answer_type`: `answer`, `restricted`, `insufficient_data`, `out_of_scope` or
  `unavailable` ("I can't reach the live data right now, so I won't guess").

### 4.5 Incident report → public map (human in the loop)

```
Staff writes: "Signal failure at Polgahawela, trains held 10 minutes"
  → Sanitise: Pydantic (5–2000 characters), no control characters, bleach rejects HTML/scripts
  → Classify (NLP): mechanical / signal_fault / weather / track_obstruction / staffing / other
  → Summarise (NLP): extractive, picks the 1–2 most important sentences
  → Saved as "pending" and embedded for RAG (so future predictions can retrieve it)
  → ADMIN reviews → Approve ("verified") or Reject ("rejected")
  → Public map feed: only verified, only TODAY (from 00:00 Sri Lanka time), only safe fields
  → Appears on the passenger map, Control Room map and Admin map (refreshed every 5 seconds)
```

**Why the admin step?** A wrong or malicious report should never reach thousands of passengers.
AI does the sorting and summarising quickly; a person makes the final decision.

**Edits:** if a verified incident is edited later, it goes back to `corrected` and **leaves the
public map** until an admin approves it again. `PATCH` can never set `verified` directly.

---

## 5. How the other three agents work

### 5.1 M1 Passenger Assistant (Thisarani)

1. **Language detection in 3 steps:**
   - Count Sinhala and Tamil Unicode letters → if present, that's the language.
   - Otherwise check a **romanized-Sinhala lexicon** (Singlish words like *mata, idala, ekak, oni*).
     Example: *"mata colomba idala badullata ticket ekak ganna oni"* = "I want a ticket from Colombo to Badulla".
   - Otherwise use `langdetect`.
2. **Intent + NER:** schedule, fare, delay, train status, booking, cancellation, policy, complaint;
   extracts stations (including Singlish aliases like *colomba*, *badullata*), train, date, time,
   class and passenger count.
3. **Conversation memory:** remembers the session language and context. If M1 asks "how many
   passengers?" and the user replies "3", M1 understands it means 3 passengers.
4. **Routing:** operations questions → M2. Fares, policies and FAQs → M1's RAG.
5. **RAG:** FAQ documents (fares, policies, schedules) split by section, embedded with
   all-MiniLM-L6-v2 into **ChromaDB**, top-3 retrieved with an intent filter, answer with citations.
6. **LLM:** Gemini or OpenRouter free models (with a fallback chain of models). The system prompt says:
   *answer only from the retrieved context, never invent a fare, time, delay or policy.* With no key,
   it shows the retrieved FAQ text directly.
7. **Accounts and privacy:** bcrypt passwords, 12-hour JWT, the passenger ID is taken **only from the
   verified token**, so you only see your own chats.

### 5.2 M3 Communication Hub, Booking and Security (Navoda)

**Hub: 9 checks on every message**

| # | Check | Why |
| --- | --- | --- |
| 1 | Schema validation | Rejects badly formed messages |
| 2 | JWT verification (signature, expiry, sender, audience) | Proves who sent it and who it is for |
| 3 | Loop guard (hop count ≤ 5) | Stops messages bouncing forever |
| 4 | Rate limit (5 per second, 30 per minute per sender) | Stops flooding |
| 5 | Allowlist (deny by default) | Only approved sender → receiver → intent combinations |
| 6 | Deduplication | Same message twice = same answer, no double booking |
| 7 | Registry lookup | Finds where the receiver lives |
| 8 | Circuit breaker (3 failures in 10 s) + 2 retries | Stops calling a broken agent |
| 9 | Audit log | Records everything with a correlation ID |

**Booking:** seat availability and fares are calculated by code, **never by an LLM**, because money
must be exact. Rules: duplicate NIC, duplicate ticket and overlapping journeys are blocked. Bookings
are **idempotent**: if you press "Confirm" twice, you still get one booking. The result is a QR
e-ticket and a confirmation email.

**Fraud detection:** 10 behaviour features (booking speed, cancellation ratio, duplicate seats,
route switching, booking time…) → **IsolationForest** (an ML model that finds unusual behaviour
without needing labelled fraud examples) → risk **LOW** = allow; **MEDIUM/HIGH** = sent to a
**human reviewer** (`PENDING_FRAUD_REVIEW`). Gemini writes a summary for the officer, but the prompt
says *"do NOT assert that the passenger committed fraud"*.

**Cancellation:** rules + RAG over 6 policy documents + a Gemini explanation → a human approves.

### 5.3 M4 Maintenance and Asset Intelligence (Primesh)

- **Health ML:** one gradient boosting model per asset type (diesel engine, bogie, brake system)
  predicts a health score from service age, fault history and sensor data.
- **NLP:** pulls key details out of technician notes.
- **RAG:** 8 maintenance manuals, pgvector or TF-IDF, top-3, re-ranked.
- **Engineer assistant:** NLP (intent + train NER, typo tolerant) → IR (live flags, inspections,
  open reports) → RAG (manual sections) → **Groq LLM (Qwen)**. Any number or ID not in the evidence →
  answer rejected → template.
- **Train flags:** M4 can mark a train `OUT_OF_SERVICE` in the shared registry. The Booking agent then
  refuses new bookings with `TRAIN_UNDER_MAINTENANCE`. M2's popup also says "This train isn't running right now".

---

## 6. How the ML model works and connects to M2

### 6.1 Simple answer
"We use a **Gradient Boosting Regressor**. It learns from 3,900 past train journeys how route,
station, time, weather, day type and incidents affect delay, and predicts the delay in minutes. On
average it is **about 2.25 minutes off**, and it explains **about 89%** of the variation in delays."

### 6.2 How gradient boosting works (plain language)
1. Start with a simple guess, e.g. the average delay.
2. Build a **small decision tree** that tries to predict the **errors** of that guess.
3. Add it to the model (scaled by a small learning rate, 0.05), so the error gets smaller.
4. Repeat **300 times**. Each new tree fixes what the previous trees got wrong.
5. The final prediction is the sum of all the trees.

**Analogy:** a group of students correcting one essay. Each one fixes the mistakes the previous
students missed, and the result is much better than any single student's version.

**Settings:** `n_estimators=300`, `max_depth=3` (small trees reduce overfitting),
`learning_rate=0.05`, `random_state=42` (repeatable results).

### 6.3 Inputs (features) and output

| Feature | Type | Values |
| --- | --- | --- |
| route | category | 7 routes |
| station | category | 17 stations |
| scheduled_hour | number | 0–23 (rush hour vs off-peak) |
| weather | category | clear, light rain, heavy rain, fog, extreme heat |
| day_type | category | weekday, weekend, public holiday |
| incident_type | category | none, signal fault, mechanical, weather, track obstruction, staffing |

**One-hot encoding:** a model needs numbers, so each category becomes its own 0/1 column
(e.g. `weather_heavy_rain = 1`, others 0).

**Output:** predicted delay in minutes.

### 6.4 Data
- **3,900 records**, 2026-03-01 → 2026-09-27, 7 routes, 17 stations.
- **Synthetic**: generated with a fixed seed (42) to look like Sri Lankan routes, weather and day types.
  A refresh script moves dates forward and adds recent records, so the data stays current.
- Split **80/20** → 3,120 training rows, 780 test rows (the model never sees test rows during training).

### 6.5 Results

| Metric | Value | Meaning |
| --- | --- | --- |
| MAE | **2.254 min** | On average the prediction is about 2¼ minutes off |
| RMSE | 2.837 min | Like MAE but punishes big errors more; close to MAE = few huge mistakes |
| R² | **0.894** | The model explains about 89% of why delays differ |

### 6.6 Feature importance (what drives delay)
1. `incident_type_none` ≈ **0.73**: whether there was **any incident at all** matters most.
2. Mechanical, staffing and track-obstruction incidents: the biggest delay spikes.
3. Clear weather and heavy rain: the next strongest factors.
4. Public holiday and scheduled hour: smaller effects.

These importances are shown in the Admin Console and used in the explanation text.

### 6.7 Why Gradient Boosting (and not others)?

| Option | Why not chosen |
| --- | --- |
| Linear Regression | Can't capture **combinations** (heavy rain + hill route + rush hour has a bigger effect than each alone) |
| Single Decision Tree | Overfits and is unstable |
| Random Forest | Good, but boosting was more accurate in our comparison |
| Deep learning | Needs far more data, slower, hard to explain (black box) |

Gradient boosting is accurate on tabular data, fast (milliseconds) and gives **feature
importances** for explanations.

### 6.8 How the model connects to M2

| Step | Where |
| --- | --- |
| Training | `ml/train_delay_model.py` → saved as `ml/delay_model.pkl` (joblib) |
| Loading | `ml/predict.py` loads it and **hot-reloads** when the file changes (no restart) |
| Used by | `/predict-delay`, passenger popup, `/passenger/query`, Ops Assistant `predict_delay` tool, Hub `delay_check` |
| Priority | Exact history first; model only when there is no real record |
| Management | Admin Console: **Retrain Now** (old model archived in `ml/model_versions/` with its metrics) and **Rollback** to any archived version |
| Fallback | No model file → median historical delay from matching records |

---

## 7. NLP in M2 (how the system "understands" text)

| NLP task | What it does | How (simple) |
| --- | --- | --- |
| Input sanitisation | Removes dangerous input | Pydantic limits, bleach rejects HTML/scripts, control characters rejected |
| Intent classification | Finds what the user wants | Keyword rules + **TF-IDF character n-gram** fallback for typos |
| Named Entity Recognition (NER) | Finds stations, trains, times, dates | Regex, alias lists, **fuzzy matching** (difflib, cut-off 0.84/0.8) |
| Incident classification | Labels incident type | Keyword rules over 6 classes (optional Claude zero-shot) |
| Extractive summarisation | Shortens incident text | Scores each sentence by important word frequency, keeps the top 1–2 |
| NLG (text generation) | Writes the answer | Templates filled with real numbers (deterministic) |
| LLM language layer | Phrases tool results for officers | Gemini, checked by the number guard |

**Why rules + TF-IDF instead of a big model for intents?** They are fast, free, explainable and
fully testable. The TF-IDF fallback handles spelling mistakes. Weakness: the incident classifier is
100% on template-style notes but only **33% on paraphrased text**; the optional LLM classifier covers that.

---

## 8. Why IR, how it works, and where it is used

### 8.1 Why IR?
- An LLM **doesn't know** our railway's incidents, manuals or policies, and it may **make things up**.
- **IR (Information Retrieval)** finds the real, relevant records first.
- **RAG (Retrieval-Augmented Generation)** = IR + using those records to write the answer.
- Benefits: **accurate**, **up to date** (new incidents are searchable immediately), **explainable**
  (we can show *which* records the answer came from), and **cheaper** (short prompts).

### 8.2 How it works

**Semantic search (main engine):**
1. Every incident note is turned into a **vector** of 384 numbers by the
   **all-MiniLM-L6-v2** sentence-transformer model. Similar meaning → similar vectors.
   ("Heavy rain flooded the track" and "track under water after storm" end up close together.)
2. Vectors are stored in Supabase with **pgvector**.
3. A query is turned into a vector too, and pgvector finds the closest ones using **cosine
   similarity** (the `match_incidents` function), keeping only matches above a threshold.

**Keyword search (offline fallback): TF-IDF.**
- **TF** (term frequency): how often a word appears in a document.
- **IDF** (inverse document frequency): rare words count more than common ones like "the".
- Documents and query become TF-IDF vectors; cosine similarity ranks them.
- Works **without internet or a database**, so retrieval never stops.

### 8.3 Where IR is used

| Where | What is retrieved | Why |
| --- | --- | --- |
| **M2** delay explanation | Top-3 similar past incidents | Explains *why* a train may be late |
| **M2** live map | Similar past incidents for a new verified incident | Estimates the delay (median) for later stops |
| **M2** Ops Assistant | Live records via tools | Answers come only from real data |
| **M1** FAQ | Fares, policies, schedules (ChromaDB) | Passenger answers with citations |
| **M3** cancellations | Policy sections (pgvector) | Grounded refund explanations |
| **M4** manuals | Manual sections, re-ranked | Engineer answers with citations |

### 8.4 Results
- **M2:** P@1 = 1.0, P@3 = 1.0, P@5 = 0.999 on 150 queries. (P@k = the share of the top-k results
  that are relevant; "relevant" = same incident type as the query.)
- **Be honest:** the independent audit used 24 new, unseen queries and got **P@1 = 0.875**, because
  our own test queries were created from the corpus itself.

---

## 9. Why we use four LLMs

| LLM / provider | Used in | Why this one |
| --- | --- | --- |
| **OpenRouter** (free models: Gemma, Qwen…) | M1 passenger chat | Most questions come from passengers → free models keep cost near zero; a **fallback chain** tries the next model if one is busy |
| **Google Gemini** (Flash / Flash-Lite) | M2 Ops Assistant, M3 booking copilot, cancellation explanations, fraud summaries; M1 option | Reliable **function calling** (needed for M2's tools), cheap and fast |
| **Groq** (Qwen) | M4 engineer assistant | **Very fast responses** (Groq runs on special LPU hardware), good for engineers in the field |
| **Anthropic Claude** (optional) | M2/M4 classification and summaries | Only used if a key is set; better than keyword rules on free-form text |

**Why not just one LLM?**
1. **Right tool for each job:** function calling (Gemini) vs. speed (Groq) vs. free high volume (OpenRouter).
2. **No vendor lock-in:** the provider is chosen in `.env`, so we can switch without code changes.
3. **Resilience:** if one provider has an outage, the other agents keep working.
4. **Free-tier limits** are spread across providers.
5. Each member could choose and test what suited their module.

**Most important point:** every LLM path has a **deterministic fallback** (templates, rule-based
routing, or raw retrieved text). Without any API key the system still works. **The LLM is only the
"voice". It never decides fares, delays, fraud or bookings.**

---

## 10. LLM and running costs: what we have to pay

### 10.1 Now (development and demo)
Almost **free**: OpenRouter free models, Gemini free tier, Groq free tier, Supabase free tier,
Upstash free tier.

### 10.2 In production: LLM prices
Approximate public prices (October 2026). Check before quoting exact numbers.

| Provider / model | Input per 1M tokens | Output per 1M tokens |
| --- | --- | --- |
| Gemini 3.5 Flash-Lite | ≈ USD 0.30 | ≈ USD 2.50 |
| Gemini 2.5 Flash-Lite (cheaper option) | ≈ USD 0.10 | ≈ USD 0.40 |
| Groq Qwen 3.8 27B | ≈ USD 0.80 | ≈ USD 4.00 |
| OpenRouter `:free` models | USD 0 (rate-limited) | USD 0 |

**What is a token?** A piece of a word; about ¾ of an English word. 1 million tokens ≈ 750,000 words.
**Input tokens** = what we send (question + data). **Output tokens** = what the LLM writes back.

### 10.3 Cost per question (worked example)
Assume one LLM call = **1,500 input tokens + 300 output tokens**.

- Gemini Flash-Lite: 1,500 × 0.30/1M = USD 0.00045, plus 300 × 2.50/1M = USD 0.00075
  → **≈ USD 0.0012 per call (≈ LKR 0.36)**
- M2 Ops Assistant uses about 3 calls per question (tool rounds) → **≈ USD 0.0036 (≈ LKR 1)**
- Groq Qwen: 1,500 × 0.80/1M + 300 × 4.00/1M → **≈ USD 0.0024 per question**

### 10.4 Example: 10-station pilot per month (estimate)

| Item | Volume / month | ≈ USD / month |
| --- | --- | --- |
| M1 passenger chat (small paid model) | 50,000 questions | 25 |
| M2 Ops Assistant | 3,000 questions | 11 |
| M3 copilot, cancellations, fraud summaries | 2,000 calls | 4 |
| M4 engineer assistant | 2,000 questions | 5 |
| **LLM subtotal** | | **≈ 45–60 (≈ LKR 15,000–18,000)** |
| Supabase Pro (database + pgvector) | | 25 |
| Upstash Redis | | 0–10 |
| Cloud server (8 Python processes) | | 40–80 |
| **Total running cost** | | **≈ USD 150 / month (≈ LKR 45,000)** |

The customer pays **LKR 850,000 / month** for this pilot, so the running cost is about 5% of revenue.

### 10.5 Why LLM cost stays low
- Most M2 passenger answers (`/passenger/ask`, `/passenger/query`) and all delay predictions use
  **no LLM**. They use ML, NLP rules and templates.
- Bookings, fares and fraud scores **never** use an LLM.
- The LLM receives only small, relevant tool results, so prompts are short.
- **Cost controls:** rate limits, max 4 tool rounds, 25-second timeout, cheap Flash-Lite models,
  and "Extra LLM usage packs" sold as an add-on if a customer uses more.

### 10.6 Other costs to mention
Staff time for support and onboarding, SMTP email, domain/SSL, backups, and occasional retraining.
These are covered by the onboarding fee and the monthly subscription.

---

## 11. Commercialisation plan

### 11.1 Business model
**B2G SaaS** (business-to-government software subscription) for railway authorities. One connected
platform replaces four separate tools. The plan is shown inside the app at **`/admin/commercial`**
with a pilot cost estimator.

### 11.2 Value proposition (why they would buy)
- Passengers get answers without queuing at counters or calling → fewer staff calls.
- Faster, verified incident alerts → better public trust.
- Delay prediction and explanations → better planning.
- Fraud screening and maintenance-aware booking → fewer losses and safer trains.
- One platform, one login system, one train registry.

### 11.3 Tiers and pricing

| | **Starter** | **Operations** (pilot tier) | **Enterprise** |
| --- | --- | --- | --- |
| Agents | M1 + basic M2 delay prediction + live board | + M2 Control Room, Admin Console, incidents, Ops Assistant + M4 | All 4 agents + M3 Booking/QR + Fraud + Hub integrations |
| Coverage | 1 route/region | 1 region, many routes | Whole network |
| Officer seats | Up to 5 | Up to 25 | Unlimited, custom roles |
| Price | **LKR 40,000 / station / month** (≈ USD 135) | **LKR 85,000 / station / month** (≈ USD 285) | Custom, from **≈ LKR 9M / year** (≈ USD 30,000) |
| Onboarding (one-time) | LKR 250,000 / region | LKR 250,000 / region | In the quote |
| Support | Business-hours email | Priority | Dedicated + SLA |
| Deployment | Cloud SaaS | Cloud or single server | Cloud, on-premise or hybrid |

- **Worked example:** 10 stations on Operations = 10 × 85,000 = **LKR 850,000/month**
  (**LKR 10.2M/year**) + **LKR 250,000** onboarding.
- **Onboarding covers:** loading timetables, manuals and policies; configuration; staff training.
- **Add-ons:** extra LLM usage packs, more languages, custom integrations, on-site training.
- Prices are **indicative planning figures** (LKR 300 = USD 1), to be finalised after a pilot.

### 11.4 Go-to-market (how we sell it)
1. **Pilot:** deploy Starter or Operations in one region with real timetables and manuals.
2. **Measure** agreed success indicators:
   - passenger questions answered without staff help
   - time from incident report to verified alert
   - delay-prediction error against actual delays
   - fraud reviews opened and confirmed
   - maintenance problems avoided
3. **Expand:** move up a tier, add regions, then negotiate an Enterprise contract.

### 11.5 Deployment options
- **Cloud SaaS:** fastest to start and update.
- **Single server / containers:** `start.py` or `docker-compose.yml` on the authority's own machines.
- **On-premise:** for data-residency contracts. Possible because every LLM path has a fallback and
  retrieval can run on local TF-IDF.

---

## 12. Responsible AI

| Principle | What it means | How RailSense does it |
| --- | --- | --- |
| **Grounding / no hallucination** | AI must not invent facts | Facts from ML, DB and retrieval; M2 and M4 **number guards**; template fallback |
| **Explainability** | Users can see *why* | Feature importances, confidence labels, similar past incidents, fraud reasons |
| **Transparency** | Users know *how* an answer was made | Citations; technique badges (LLM, NLP, IR, RAG, ML, XAI); `answer_method` stored; "estimate, not a live signal" wording |
| **Human in the loop** | People make important decisions | Admin approves public incidents; humans review fraud and cancellations |
| **Fairness** | Everyone treated equally | Multilingual, no personal data in ML, non-accusing fraud summaries (Section 13) |
| **Accountability** | Actions can be traced | Hub audit log, officer audit log, audit events, Ops Assistant history; read-only |
| **Privacy** | Personal data protected | HMAC NICs, bcrypt, allowlisted public fields, secrets server-side (Section 14) |
| **Safety / misuse prevention** | Stop abuse | Sanitisation, rate limits, role-filtered tools, fixed refusals, prompt-injection tests |
| **Honesty** | Don't overclaim | Synthetic data declared; independent audit published next to our own numbers |

**Simple way to say it:** "AI suggests, data proves, humans decide, and everything is logged."

---

## 13. System-side fairness: what fairness users get

1. **Language fairness:** answers in Sinhala, Tamil or English, matching the user's language. People
   **without a Sinhala keyboard** can type Singlish (56 test queries, 100% correct).
2. **No personal data in predictions:** the delay model only uses route, station, time, weather, day
   type and incident type. Name, age, gender, ethnicity or NIC never go into a prediction, so it
   **cannot discriminate between people**.
3. **Fraud fairness:**
   - The model only **flags** unusual behaviour; a **human decides**.
   - The LLM summary must **not accuse** anyone and must mention legitimate reasons (group travel,
     travel agents).
   - Fraud is judged on booking behaviour, not on who the person is.
4. **Deterministic, equal rules:** fares, seat availability and booking rules are code, so the same
   input gives the same result for everyone.
5. **Same information for all:** every passenger sees the same verified incidents and live board.
6. **Fair role access for officers:** each role gets exactly its permissions; restricted questions
   get a clear 🔒 explanation instead of a confusing error.
7. **Access when AI fails:** fallbacks mean users still get answers when an LLM is unavailable.
8. **Known gap (say this honestly):** M1's Sinhala/Tamil FAQ retrieval is weaker than English
   (P@1 0.375 / 0.250 vs 1.0) because the embedding model is English-only. Fix: multilingual
   embeddings. M1 also forwards only English operations questions to M2.

---

## 14. Data privacy, data leakage and protecting sensitive data

### 14.1 What is sensitive here?
NIC numbers, names, emails, phone numbers, passwords, booking details, internal incident notes,
reviewer names, audit data, API keys and secrets.

### 14.2 How each is protected

| Data | Protection | Explanation |
| --- | --- | --- |
| **NIC numbers** | **HMAC-SHA256 hashing + masking** | The NIC is turned into a one-way code using a secret key; you can't get the NIC back. Duplicate checks compare codes. When shown, it is masked (e.g. `20****1234`). Say "hashing", not "AES encryption". |
| **Passwords** | **bcrypt** (12 rounds) | One-way, salted and deliberately slow, so stolen hashes are hard to crack |
| **Logins** | Signed, expiring **JWT** | Officers 8 h, passengers 12 h; can't be forged without the secret |
| **Chats** | Ownership from the token | A passenger's ID comes **only from the verified token**, never from the request, so you can't read someone else's chats |
| **Public incident map** | Admin approval + today-only + **field allowlist** | Only `id, train, station, lat, lon, type, summary (≤180 chars), verified_at, status` leave the server; raw text, reviewer names and internal IDs never do |
| **Secrets / API keys** | `.env` (git-ignored), server-side only | Database keys, JWT and HMAC secrets never reach the browser; the gateway signs Hub messages on the server |
| **Data sent to LLMs** | Role-filtered, minimal | The LLM gets only the tool results needed; admin-only data never enters an engineer's session; M3 copilot masks private fields first |
| **Agent messages** | Hub JWT + allowlist | Sender and audience checked; deny by default |
| **Audit logs** | Read-only | No update/delete routes (write verbs return 405) |

### 14.3 How data leakage is prevented
- **Leakage to the public:** admin approval, allowlist, today-only filter. We **avoided Supabase
  Realtime** because it would stream whole database rows (including internal fields) to the
  unauthenticated passenger page. We use 5-second polling of a safe, filtered feed instead.
- **Leakage between users:** chat ownership from the token; per-officer assistant history.
- **Leakage between roles:** RBAC on every route and every LLM tool.
- **Leakage through the LLM:** the LLM only sees minimal, role-allowed data; free text without tool
  calls is never shown; prompt-injection tests in M1 (12 of 15 pass, the 2 failures are documented).
- **Leakage through code:** `.env` files and secrets are git-ignored; `.env.example` holds only key names.
- **Input attacks:** validation, bleach, length limits and rate limits stop script injection and flooding.

### 14.4 Privacy by design
Collect only what is needed. ML uses no personal data. Project data is synthetic. On-premise
deployment is possible when data must stay in the country.

---

## 15. How to identify whether a record comes from the system or not

**Simple answer:** "Every answer and record carries a label showing where it came from, and our
number guard guarantees that every number shown exists in the system's data."

| # | Method | How it works |
| --- | --- | --- |
| 1 | **Source label** | Responses include `source` / `data_source`: `supabase` (live database), `local_fallback` / `local_csv` / `local_jsonl` (offline copy) or `unavailable`. Screens show **"Offline mode — showing local data"**; the map shows **"Offline · last known"** with `stale: true` |
| 2 | **Citations** | Each Ops Assistant answer lists the **tool** that produced the data (e.g. `get_route_status`); citations and stat chips are built by code |
| 3 | **`answer_method`** | Stored per answer: `llm_tool_calling` (LLM phrased real data), `template_after_guard` (LLM answer rejected, template shown), `rule_based_fallback` (no LLM) |
| 4 | **Technique badges** | LLM · NLP · IR · RAG · ML · XAI badges are computed from what actually ran |
| 5 | **Number guard** | Any number not in the system's data blocks the LLM answer, so every number shown is from the system |
| 6 | **Train registry check** | Train IDs are checked against the Supabase `trains` table; unknown IDs are rejected (and M4 rejects made-up IDs in LLM text) |
| 7 | **Incident status** | `pending` / `corrected` / `verified` / `rejected`. Only `verified` (admin-approved) is public; the browser also drops anything not marked VERIFIED |
| 8 | **Model version** | Each prediction includes `model_version`, showing which trained model produced it |
| 9 | **Confidence label** | HIGH = real recorded journey; MEDIUM/LOW = ML prediction |
| 10 | **Hub audit + signatures** | Every agent message has `message_id`, `correlation_id`, sender, receiver and a **JWT signature**; unsigned or forged messages are rejected and the rejection is logged |
| 11 | **Corpus IDs** | Records added by the refresh script have deterministic `uuid5` IDs, so re-running never creates duplicates |

---

## 16. Security: roles, tokens and the Hub

### 16.1 RBAC (role-based access control) in M2

| Permission | Admin | Ops Engineer | Purpose |
| --- | --- | --- | --- |
| `m2.control_room.view` / `.action` | ✔ | ✔ | Control Room, dashboard, incidents |
| `m2.prediction.view` / `.run` | ✔ | ✔ | Delay prediction |
| `m2.assistant.use` | ✔ | ✔ | Operations Assistant |
| `m2.incidents.review` | ✔ | — | Approve/reject incidents |
| `m2.model.manage` | ✔ | — | Retrain, rollback, metrics |
| `m2.audit.view` | ✔ | — | Audit log |
| `m2.system.config` | ✔ | — | System health |
| `m2.officers.*` | ✔ | — | Officer and role management |

Six other predefined roles exist (operations manager, dispatcher, maintenance officer, security
officer, analyst, viewer). **The last active admin can't be deactivated or demoted**, so the system
can never be locked out.

### 16.2 Login flow
Officer enters a password → compared with the **bcrypt** hash → server issues a **signed JWT**
containing the role and expiry → every request sends it in the `Authorization` header →
`require_permission()` checks the right permission.

### 16.3 Agent-to-agent security
Signed JWT `AgentMessage` → Hub's 9 checks (Section 5.2). A sender can't pretend to be another agent,
because the token's `sub` must match `sender_agent`.

### 16.4 Input security
Pydantic type and length limits, bleach, control-character checks, slowapi rate limits (M2, M4), Hub
rate limits, deduplication and idempotent bookings.

---

## 17. Assignment requirement checklist

| Requirement | Where it is implemented |
| --- | --- |
| **LLMs** | M1 (OpenRouter/Gemini), M2 Ops Assistant (Gemini function calling), M3 (Gemini), M4 (Groq Qwen) |
| **NLP** | Language detection, intent classification, NER, incident classification and extractive summarisation (M2), technician-note extraction (M4), NIC normalisation (M3), template NLG |
| **IR** | pgvector + TF-IDF (M2), ChromaDB (M1), manual retrieval (M4), policy retrieval (M3) |
| **RAG** | M2 explanations and map delay sizing, M1 FAQ, M3 cancellations, M4 manuals |
| **ML** | M2 GradientBoosting delay, M4 HistGradientBoosting health, IsolationForest fraud |
| **Security** | JWT, bcrypt, RBAC, HMAC NIC, sanitisation, rate limits, circuit breakers, audit |
| **Agent protocol** | JWT-signed `AgentMessage` through the Hub, `/register` handshake, Upstash pub/sub |
| **Responsible AI** | Sections 12–15 |
| **Commercialisation** | Section 11 and `/admin/commercial` |

---

## 18. Evaluation results explained

| Component | Result | What it means |
| --- | --- | --- |
| **M2 delay model** | MAE **2.254 min**, RMSE 2.837, R² **0.894** (3,900 records) | About 2 minutes off on average; explains about 89% of variation |
| **M2 incident classification** | 100% on 400 template records; 33% on 6 paraphrased samples | Rules are perfect on known wording but weak on new wording |
| **M2 incident retrieval** | P@1 1.0, P@3 1.0, P@5 0.999 (150 queries); audit P@1 0.875 | The top result is almost always relevant |
| **M2 tests** | **57 passed** | Approval workflow, map privacy, midnight cut-off, guard, roles, live tracker, passenger NLP |
| M1 romanized Sinhala | 100% (56 queries) | Language, intent, origin and destination all correct |
| M1 prompt injection | 12 pass / 2 fail of 15 | Mostly resistant; 2 documented gaps |
| Security fraud model | Accuracy 99.17%, recall 100%, precision 93.5% (600 samples) | Catches every fraud case; a few false alarms, which humans review |
| M4 health model | avg R² 0.915, avg MAE 3.20 (1,440 rows) | Accurate health scores |
| M4 note NLP | 89.8% | Good extraction from technician notes |
| M4 manual retrieval | P@1/3/5 = 1.0 (audit P@1 0.792) | Strong on its own set, lower on new queries |
| Independent audit | 16 tests: 6 PASS, 7 PARTIAL, 3 FAIL | Published openly with mitigations |

**Metric definitions:**
- **MAE (Mean Absolute Error):** average size of the error.
- **RMSE (Root Mean Squared Error):** like MAE, but big mistakes count more.
- **R²:** share of variation explained (1.0 = perfect, 0 = no better than guessing the average).
- **Precision:** of the bookings we flagged, how many were really fraud.
- **Recall:** of all the real frauds, how many we caught.
- **P@k:** share of the top-k retrieved results that are relevant.

---

## 19. Resilience: what happens when something fails

| If this fails | M2 keeps working by… |
| --- | --- |
| Supabase database | Local CSV and JSONL files |
| pgvector search | Local TF-IDF retrieval |
| ML model file | Median historical delay |
| Gemini | Keyword router with the same role rules |
| Hub | Alerts kept in memory, M2 continues |
| Upstash Redis | Alert publishing skipped cleanly |
| Map CDN (Leaflet tiles) | Plain list of verified incidents |
| Map feed | Last known feed marked "Offline · last known", still cut at midnight |
| WebGL (3D banners) | Static panel, all data still shown |

**Why it matters:** in a demo or a real control room, one cloud outage shouldn't take down the whole system.

---

## 20. Pros and cons

### Pros
- **One platform, four agents**, one passenger side and one officer side.
- **Grounded answers:** the LLM can't invent numbers (number guards, templates).
- **Explainable:** confidence, feature importances, similar incidents, citations, badges.
- **Multilingual**, including Singlish for people without a Sinhala keyboard.
- **Secure:** JWT-signed agent messages, RBAC, bcrypt, HMAC NICs, audit logs.
- **Resilient:** works offline and without LLM keys.
- **Cheap to run:** most M2 answers need no LLM.
- **Human in the loop** for public alerts, fraud and cancellations.
- **Modular:** can be sold tier by tier; LLM providers can be swapped through config.
- **Well tested:** 57 M2 tests, M1 and M3 test suites, an independent audit.

### Cons / limitations (examiners like honesty)
- **Synthetic data**, not real Sri Lanka Railways data → real-world accuracy unknown until a pilot.
- Incident classifier: 100% on templates but **33% on paraphrased text**.
- Sinhala/Tamil retrieval weaker than English (English-only embeddings).
- Intermediate station times **estimated from track distance**, not an official per-stop timetable.
- M1 forwards only **English** operations questions to M2.
- **Open audit findings:**
  - the default M2 admin password stays active if `ADMIN_INITIAL_PASSWORD` isn't set
  - some admin, fraud and Hub endpoints can be reached without auth on the public port
  - M4 has hard-coded engineer credentials
  - CORS is too open
  - mitigations are in `student4_audit/findings.md`
- M4 isn't yet connected to the shared database, so its flags don't reach Booking yet (the block
  itself works through the shared registry).
- The Hub rate limiter is in-memory (one server only); multiple servers need Redis.
- Several LLM providers = several API keys to manage.

---

## 21. Challenges we faced and how we solved them

| Challenge | What went wrong | How we solved it |
| --- | --- | --- |
| **LLM hallucination** | LLMs invented delay times and numbers | Facts from ML + DB + retrieval; number/ID guards; template fallback |
| **Integrating 4 members' work** | Each agent was built separately | One Hub protocol (`AgentMessage` + JWT), one shared train registry, one launcher |
| **Different train IDs per module** | Same train had different IDs | Supabase `trains` table as the single source of truth + validation scripts |
| **Port conflicts on different laptops** | Services clashed with other programs | `start.py` picks free ports; pages use the gateway `/svc/...` |
| **Package/version problems** | ChromaDB index needed an exact version; Windows Smart App Control blocked venvs | M1 has its own pinned venv; others share one Python; `check_setup.py` shows what's missing |
| **No real railway data** | Can't get official operational data | Synthetic generator with a fixed seed + corpus refresh script |
| **Overnight trains and "today"** | A 19:15 → 04:30 train looked "departed" in the evening | One clock (Asia/Colombo), overnight logic in the live tracker, tests |
| **Unverified incidents reaching the public** | Raw staff notes are sensitive | Admin approval, allowlist, today-only filter |
| **Users without a Sinhala keyboard** | Singlish wasn't understood | Romanized-Sinhala lexicon and station aliases |
| **Free-tier rate limits / outages** | LLM calls failed during testing | Fallback model chains and deterministic fallbacks |
| **Typos in questions** | Intent rules missed misspelt words | TF-IDF character n-gram fallback + fuzzy station matching |
| **Secure agent communication** | Agents could be impersonated | JWT with sender/audience binding, allowlist, dedup, rate limit, audit |
| **Slow start-up** | Embedding model download stalled start-up | Cached model; offline mode when cached |

---

## 22. Future work

- Real Sri Lanka Railways data and official per-stop timetables.
- Multilingual embeddings for Sinhala/Tamil retrieval; relevance cut-offs.
- SMS / mobile push notifications from `delay_alert` and `maintenance_alert`.
- Route Sinhala/Tamil operations questions and maintenance questions from M1 to M2 and M4.
- Fix the open audit findings; TLS/mTLS between services; field encryption at rest.
- Redis-backed Hub rate limiting for multiple servers; mobile app and station kiosks.
- An LLM classifier for paraphrased incident reports.

---

## 23. Tech stack

| Layer | Technologies |
| --- | --- |
| Backend | Python, FastAPI, Uvicorn, Pydantic v2 |
| ML | scikit-learn (GradientBoosting, HistGradientBoosting, IsolationForest), joblib |
| NLP | Keyword rules, TF-IDF, langdetect, regex and fuzzy NER (difflib), extractive summarisation |
| IR / RAG | sentence-transformers all-MiniLM-L6-v2, Supabase pgvector, ChromaDB, TF-IDF fallback |
| LLMs | OpenRouter, Google Gemini, Groq (Qwen), optional Claude |
| Data | Supabase PostgreSQL, Upstash Redis, local CSV/JSONL fallbacks |
| Security | PyJWT, bcrypt, bleach, slowapi, HMAC-SHA256 |
| Frontend | HTML/JS portals, React (M1 chat), Leaflet + OpenStreetMap, Three.js (3D banners), Next.js (homepage) |
| Launch / deploy | `start.py`, `docker-compose.yml` |

---

## 24. Likely viva questions with full answers

**Q1. What did you build?**
"I built M2, the Operations and Delay Prediction agent. It has a gradient boosting delay model; a
live train tracker; NLP that understands passenger operations questions; incident classification
and summarisation; pgvector and TF-IDF retrieval for grounded explanations; an admin approval
workflow with a today-only public incident map; and an Operations Assistant that uses Gemini
function calling with a number guard. It also has the Control Room and Admin Console with RBAC,
retraining and rollback. As team leader I integrated all four modules through a shared train
registry, the gateway and the `start.py` launcher."

**Q2. Walk me through what happens when a passenger asks "Is my train late?"**
Use Section 4.1: M1 language + intent + NER → M2 `/passenger/query` → M2 intent + NER → live tracker,
verified incidents, history or ML → template answer → M1 → passenger.

**Q3. How does your LLM avoid hallucination?**
"The LLM never sees the database directly. It can only call fixed tools that return real data. After
it writes an answer, a number guard checks that every number exists in the tool results. If one
doesn't, we discard the LLM text and show a template built by code. Text written without any tool
call is never shown, and citations are generated by code."

**Q4. What if the LLM is down?**
"A keyword router picks the same tools with the same role rules, and templates write the answer.
Passengers' M2 answers don't use an LLM at all."

**Q5. Why RAG instead of just asking the LLM?**
"The LLM doesn't know our incidents, manuals or policies, and it can make things up. RAG retrieves
the real evidence first, so answers are accurate, current and can be cited."

**Q6. What's the difference between IR and RAG?**
"IR is finding the relevant documents. RAG is IR plus giving those documents to a generator to
write the answer."

**Q7. Why both pgvector and TF-IDF?**
"pgvector understands meaning, so 'flooded track' matches 'water on the line'. TF-IDF works with no
internet, no database and no model, so retrieval never stops."

**Q8. Why Gradient Boosting?**
"Delays come from combinations of factors that linear models miss. Deep learning needs much more data
and can't be explained easily. Gradient boosting is accurate on tabular data, fast, and gives
feature importances for explanations. It beat Linear Regression, Decision Tree and Random Forest in
our comparison."

**Q9. What do MAE 2.25 and R² 0.894 mean?**
"On average a prediction is about 2¼ minutes off, and the model explains about 89% of the
variation in delays."

**Q10. Is your data real?**
"No, it's synthetic, generated with fixed seeds to reflect Sri Lankan routes, weather and day types.
We say this openly. A pilot with real data is the next step, and the model can be retrained from the
Admin Console."

**Q11. How do you handle overfitting?**
"An 80/20 train/test split, so the test data is never used for training; small trees
(`max_depth=3`); a low learning rate (0.05); and RMSE close to MAE, which shows there are no huge
outlier errors."

**Q12. How is the system fair?**
"It answers in the user's language, including Singlish. The ML uses no personal data. Fraud is only
flagged, and a human decides. Fares and booking rules are deterministic, so they are the same for
everyone. We also admit our Sinhala/Tamil retrieval gap."

**Q13. How do you protect NICs?**
"HMAC-SHA256 hashing with a secret key, plus masking when shown. Duplicate checks compare hashes.
The secret is never in git or the browser."

**Q14. How do you stop data leaking to the public?**
"Admin approval, a today-only filter and a field allowlist on the map feed; no Realtime row streaming;
secrets kept on the server; role-filtered LLM tools; chat ownership from verified tokens."

**Q15. How do you know an answer came from the system?**
Use Section 15: source labels, citations, `answer_method`, badges, number guard, model version,
incident status, Hub signatures.

**Q16. How do agents communicate securely?**
"Through the Hub, using a JWT-signed `AgentMessage`. The Hub checks schema, signature, sender,
audience, allowlist, rate limits, duplicates and loops, then logs everything."

**Q17. Is it MCP?**
"It's MCP-inspired. It's our own JWT-signed message envelope over HTTP/JSON with a schema version."

**Q18. How do roles work?**
"Officers sign in with bcrypt-checked passwords and receive a signed token with their role. Every
route and every assistant tool checks a permission; for example, approving incidents needs
`m2.incidents.review`, which only admins have. The last admin can't be removed."

**Q19. Why do you use four LLMs?**
Section 9: right tool per job, no lock-in, resilience, free-tier spread, and each one has a fallback.

**Q20. How much does it cost and how do you make money?**
"Running a 10-station pilot costs about USD 150 a month, with LLMs about USD 45–60 of that. The
customer pays LKR 850,000 a month on the Operations tier plus LKR 250,000 onboarding. We start with a
pilot, measure agreed indicators, then expand."

**Q21. What did the independent audit find?**
"16 tests: 6 pass, 7 partial and 3 fail. We published it next to our own numbers. Chat ownership is
already fixed. The rest have documented mitigations: set `ADMIN_INITIAL_PASSWORD`, add auth on
admin endpoints, tighten CORS and remove hard-coded credentials."

**Q22. Why only today's incidents on the map?**
"Passengers care about current disruption. The cut-off is 00:00 Sri Lanka time, recalculated on every
request, so old markers vanish at midnight. Tests check 23:59 versus 00:01."

**Q23. How does M4 affect booking?**
"M4 marks a train OUT_OF_SERVICE in the shared registry, and Booking blocks new bookings with
TRAIN_UNDER_MAINTENANCE."

**Q24. What happens when a booking looks fraudulent?**
"IsolationForest gives a risk level. MEDIUM or HIGH sends it to PENDING_FRAUD_REVIEW and a human
decides. The LLM summary is not allowed to accuse the passenger."

**Q25. What would you improve with more time?**
Section 22: real data, multilingual embeddings, SMS alerts, fixing the audit findings, TLS between services.

**Q26. What was the hardest part?**
"Integration: four people's agents needed one train ID system, one secure protocol and one launcher
that works on every laptop. The second hardest was stopping the LLM from inventing numbers, which we
solved with the number guard."

---

## 25. Demo order (if asked to show)

1. `python start.py` → all services show ready.
2. `localhost:3000/user` → live train board → **Delay** popup on a train.
3. M1 chat: an English operations question (answered by M2) and a Singlish question.
4. `localhost:3001/login` → Control Room → delay prediction with explanation and similar incidents.
5. Submit an incident → Admin Console → **Approve** → it appears on the passenger map.
6. Operations Assistant: ask as admin, then ask about the audit log as engineer → 🔒 restricted.
7. Admin Console → model metrics, retrain/rollback, audit log.
8. Booking → QR ticket; Hub monitor; `/admin/commercial`.

---

## 26. Key terms glossary

| Term | Plain meaning |
| --- | --- |
| **Agent** | An independent AI service with one job (e.g. M2 operations) |
| **LLM** | Large Language Model, an AI that writes text (Gemini, Qwen…) |
| **Function calling** | The LLM picks a tool to run instead of answering from memory |
| **NLP** | Natural Language Processing: making computers understand text |
| **Intent** | What the user wants (e.g. check a delay) |
| **NER** | Named Entity Recognition: finding names like stations, trains and dates in text |
| **IR** | Information Retrieval: finding the most relevant documents |
| **RAG** | Retrieval-Augmented Generation: retrieve evidence first, then write the answer from it |
| **Embedding** | A list of numbers that represents the meaning of text |
| **pgvector** | PostgreSQL extension for storing embeddings and finding similar ones |
| **TF-IDF** | Keyword-weighting method; rare, important words count more |
| **Cosine similarity** | Measures how close two vectors point in the same direction (1 = same meaning) |
| **Gradient boosting** | Many small trees, each fixing the previous trees' mistakes |
| **IsolationForest** | ML model that finds unusual (outlier) behaviour |
| **One-hot encoding** | Turning categories into 0/1 columns |
| **JWT** | Signed token that proves who you are and expires |
| **bcrypt** | Slow, salted one-way password hashing |
| **HMAC-SHA256** | One-way hashing with a secret key |
| **RBAC** | Role-Based Access Control: permissions by role |
| **Allowlist** | Only listed things are allowed; everything else is denied |
| **Circuit breaker** | Stops calling a failing service for a while |
| **Idempotent** | Doing the same action twice has the same effect as once |
| **Hallucination** | When an LLM invents false information |
| **Grounding** | Making sure an answer is based on real evidence |
| **Human in the loop** | A person approves important AI decisions |
| **B2G SaaS** | Software sold as a subscription to government organisations |

**Good luck! Give the simple answer first, then one technical detail, and be honest about limitations.**
