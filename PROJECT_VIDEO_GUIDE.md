# RailSense AI — 3½-Minute Project Video: Production Guide

> **Course:** IT3041 – Information Retrieval & Web Analytics · SLIIT
> **Length:** 3:30 (hard cap 3:40) · **Format:** 1920×1080, 30 fps, MP4 (H.264 + AAC)
> **Covers:** the whole platform: M1 Passenger Assistant, M2 Operations, M3 Hub + Booking, Security & Fraud, M4 Maintenance, and the unified portals.
> **Presenter / narrator:** team leader (Pasindi), with each member optionally recording their own module's voice-over.

This guide is the single source for recording the video: the storyboard with exact timings, the full narration script, the on-screen actions and URLs for every shot, a pre-flight checklist, the evidence figures to show, and the editing plan. Every feature listed here exists in the current code; nothing in the script is hypothetical.

---

## 1. Story in one sentence

*RailSense AI is five cooperating AI agents behind one secured Hub that tell passengers **how late** a train is and **why**, let them book safely, and give staff one place to predict delays, approve incidents, review fraud and keep the fleet healthy, with every number coming from real models and data.*

The video follows one day on the network: **passenger → booking → operations → maintenance → administration → evidence**.

---

## 2. Timing overview (3:30)

| # | Time | Duration | Segment | Modules shown | Words |
|---|---|---|---|---|---|
| 1 | 0:00 – 0:12 | 12 s | Title + problem | — | ~28 |
| 2 | 0:12 – 0:30 | 18 s | Architecture | All | ~42 |
| 3 | 0:30 – 1:16 | 46 s | Passenger portal + M1 quick ask and signed-in assistant | Gateway, M1, M2 | ~112 |
| 4 | 1:16 – 1:39 | 23 s | Booking, fraud screening, cancellation | M3 Booking, Security | ~55 |
| 5 | 1:39 – 2:27 | 48 s | Operations Control Room + Admin Console | M2 | ~115 |
| 6 | 2:27 – 2:55 | 28 s | Maintenance & asset intelligence | M4 (+ M3 effect) | ~65 |
| 7 | 2:55 – 3:12 | 17 s | Central admin portal + Hub audit | Gateway, M3 Hub, Security | ~38 |
| 8 | 3:12 – 3:30 | 18 s | Evidence + close | All | ~40 |

Narration: **about 450 words ≈ 3:12 spoken at ~140 words/minute**, leaving ~18 s for pauses, the title and the slides. If it runs long, drop the optional M4 booking-block shot (6c). Speed typing and form filling up 2× in editing so the narration never waits for the screen.

---

## 3. Pre-flight checklist (do this 15 minutes before recording)

**Services**

- [ ] From the repo root run `.\start_all.ps1` (M1 :8001, Hub :8002, Booking :8003, Security :8004, M2 :8005, M4 :8006, Gateway :3000, React chat :5173).
- [ ] Confirm health: `http://localhost:8005/health`, `http://localhost:8006/health`, `http://localhost:8002/health` all return 200.
- [ ] Supabase reachable (M2 Control Room shows **SUPABASE LIVE**; the admin portal shows 6/6 agents online).
- [ ] `GEMINI_API_KEY` and `GEMINI_MODEL` set in `.env` (M1 multilingual answers, M2 Operations Assistant, M3 admin booking chat).

**Browser**

- [ ] Chrome, window exactly 1920×1080, zoom 100%, bookmarks bar hidden, notifications off.
- [ ] Hard-refresh every page once (**Ctrl + F5**) so the newest UI loads.
- [ ] Window A (normal): signed in as an **administrator** on `localhost:3000/admin` and `localhost:8005/admin`.
- [ ] Window B (incognito): signed in as an **Operations Engineer** on `localhost:8005/`.
- [ ] Window C: passenger portal `localhost:3000/user` and the M1 Passenger Assistant `localhost:5173`, signed in with **two or three earlier conversations already in the sidebar** so saved history is visible.
- [ ] Pre-open all tabs in storyboard order (section 5) so no URL is typed on camera.

**Demo data**

- [ ] One train and station for the whole video: **Podi Menike (1005) at Ella** (Colombo Fort → Badulla line).
- [ ] Clear old demo incidents so today's map starts nearly empty.
- [ ] One pending fraud case in the admin queue (create it during rehearsal if needed).
- [ ] Rehearse the M4 "flag train out of service" step, then **clear the flag** so the booking desk works again.

**Recording**

- [ ] OBS: 1080p30 canvas, capture the browser window only, cursor highlight on, microphone at −12 dB peak.
- [ ] Record each segment as its own clip; record the narration separately afterwards if the live voice is uneven.

---

## 4. Evidence figures (use exactly these; all come from committed evaluation files)

| Module | Model / technique | Result | Source |
|---|---|---|---|
| M2 Operations | Delay prediction (GradientBoostingRegressor, 3,000 trips) | MAE 2.24 min · R² 0.87 | `M2-operations-agent/evaluation/ml/` |
| M2 Operations | Incident retrieval (pgvector / TF-IDF, 150 queries) | P@1 1.000 · P@5 0.999 | `M2-operations-agent/evaluation/rag/` |
| M2 Operations | Automated tests | 40 / 40 passing | `M2-operations-agent/tests/` |
| M4 Maintenance | Health model (per-asset-type HistGBR, 1,440 rows) | Avg MAE 3.20 · avg R² 0.915 | `M4-maintenance-agent/evaluation/ml/health_model_metrics.json` |
| M4 Maintenance | Technician-note NLP (118 notes) · manual retrieval | 89.8% accuracy · P@1 1.000 | `M4-maintenance-agent/evaluation/` |
| Security & Fraud | IsolationForest (600 records) | 99.17% accuracy · 100% recall | `security-agent/evaluate_model.py` (root README) |

> Re-run the evaluation scripts before recording if any model was retrained, and update this table if the numbers moved.

---

## 5. Storyboard and narration

Each scene: **what the viewer sees**, **what you do**, **what you say**, **on-screen caption** (lower-third added in editing).

### Scene 1 — Title and problem (0:00 – 0:12)

| Visual | Action |
|---|---|
| Passenger portal hero at `localhost:3000/user` (3D robot, "Your railway journey, powered by AI."), then the title card | Let the robot animate 2 s, fade to **RailSense AI — Multi-Agent Railway Intelligence** |

**Narration:**
> "Passengers rarely know how late their train is, or why, and staff juggle separate tools. RailSense AI brings it together: five AI agents that answer from real data, never guesses."

**Caption:** `RailSense AI · IT3041 · SLIIT`

### Scene 2 — Architecture (0:12 – 0:30)

| Visual | Action |
|---|---|
| Architecture diagram slide (the Mermaid diagram from the root `README.md`) | Highlight each box as it is named |

**Narration:**
> "Every agent message passes through the M3 Communication Hub, which verifies a signed token, validates and logs it. M1 serves passengers, M2 runs operations, M3 handles bookings, the Security agent scores fraud, and M4 watches the fleet, all sharing one Supabase train registry."

**Caption:** `JWT-secured Hub · 6 FastAPI services · Supabase + pgvector`

### Scene 3 — Passenger experience (0:30 – 1:16)

| # | Visual / URL | Action |
|---|---|---|
| 3a | `localhost:3000/user` → **Today's services** | Click **Delay** on Podi Menike: popup with delay gauge, expected arrival and reason |
| 3b | Popup input | Type **"why might it be late?"** → cited reason |
| 3c | Scroll to **Incidents on the network** | 2 s on the map |
| 3d | Hero of `localhost:3000/user` → **Ask AI →** | Quick ask without signing in: type a one-off question, e.g. "What time is the next train to Kandy?" |
| 3e | `localhost:5173` (M1 Passenger Assistant, signed in) | Ask in Sinhala, e.g. **"මහනුවර යන ඊළඟ දුම්රිය කීයටද?"** ("When is the next train to Kandy?"). Test the phrase in rehearsal and keep one that returns a schedule. Then open the **sidebar** and click an earlier conversation to show saved history |

**Narration:**
> "On the passenger portal, tap Delay on any train. M2 predicts how late it will be, when it will arrive, and why, from its delay model and past incidents, in plain language. The map below shows only disruptions staff have confirmed today.
> Occasional travellers can ask the M1 assistant straight from the home page, no account needed. Regular passengers sign in and get the full Passenger Assistant, where every conversation is saved and can be reopened. It chats in English, Sinhala or Tamil, answers schedules and fares from its knowledge base with citations, and asks M2 through the Hub for delays."

**Captions:** `M2 · delay model + template NLG` → `M1 · quick ask, no login` → `M1 · signed in · saved chat history · multilingual NLU · ChromaDB RAG`

### Scene 4 — Booking, fraud screening and cancellation (1:16 – 1:39)

| # | Visual / URL | Action |
|---|---|---|
| 4a | `localhost:3000/user/booking` | Search Colombo Fort → Badulla, pick a train and seat class (speed 2×) |
| 4b | Payment → `localhost:3000/user/confirmation` | **Reservation Confirmed & Paid** e-ticket with passenger manifest |

**Narration:**
> "The M3 Booking Agent holds seats and calculates fares deterministically, so prices are never invented. Every booking is scored by the Security agent's IsolationForest model; suspicious ones are held for human review or rejected. Cancellations are never automatic: an administrator reviews each one."

**Caption:** `M3 Booking · Security · IsolationForest · human review`

### Scene 5 — Operations: M2 Control Room and Admin Console (1:39 – 2:27)

| # | Visual / URL | Action |
|---|---|---|
| 5a | Window B `localhost:8005/` | 3 s on the **3D banner**: Loco the train robot points at the tallest corridor bar |
| 5b | **Delay prediction & RAG** | Route → Train → Station dropdowns, **Run prediction**: delay, explanation, similar incidents |
| 5c | **Incident management** → Report incident | Station **Ella**, type "Podi" → **Podi Menike · 1005**, describe a signal fault → *pending* |
| 5d | Window A `localhost:8005/admin` → Incidents | **Approve** → cut to the passenger map: the marker appears |
| 5e | Window B assistant | Ask **"Show me the audit log"** → 🔒 *Administrator only* |

**Narration:**
> "Staff work in the M2 Control Room, where Loco, our train-robot guide, reads the live data: each bar is a real corridor's average delay. In the prediction lab, M2's gradient boosting model, R-squared 0.87, predicts a delay and explains it with similar incidents found by vector search.
> Staff report incidents by picking the train by name; NLP classifies and summarises them. Nothing goes public until an administrator approves, and then it appears on every map within five seconds.
> The Operations Assistant answers only from live data and respects roles: an engineer asking for the audit log is told it's for administrators."

**Captions:** `M2 · R² 0.87 · pgvector RAG P@1 1.00` → `Approve → public map in ≤ 5 s` → `Role-aware, number-grounded assistant`

### Scene 6 — Maintenance and asset intelligence: M4 (2:27 – 2:55)

| # | Visual / URL | Action |
|---|---|---|
| 6a | `localhost:8006/` | Asset dashboard; run a health prediction for a diesel engine |
| 6b | Field reports | A passenger-reported issue that arrived from M1 via the Hub |
| 6c | Flag a train out of service | (Optional 2 s) booking desk refuses it with *TRAIN_UNDER_MAINTENANCE*; **clear the flag after** |

**Narration:**
> "M4 keeps the fleet safe. It scores each asset's health with per-type gradient boosting models, R-squared 0.92 on average, backed by the equipment manuals it retrieves. Passenger complaints arrive as field reports through the Hub, and when an engineer flags a train out of service, booking stops selling seats on it immediately."

**Caption:** `M4 · per-type HistGBR · manual RAG · out of service → bookings blocked`

### Scene 7 — Central admin portal (2:55 – 3:12)

| # | Visual / URL | Action |
|---|---|---|
| 7a | `localhost:3000/admin` | 2 s on the **Command Deck** 3D hero |
| 7b | Bookings & Revenue → **Security & Fraud Review Queue** | Approve one case |
| 7c | Hub Monitor → **Audit Trail** | Scroll past ROUTED / REJECTED messages |

**Narration:**
> "Administrators run everything from one portal: the command deck shows the network, today's incidents and all six agents' health, alongside the fraud and cancellation queues and a full audit trail of every Hub message."

**Caption:** `Unified admin portal · human-in-the-loop · full audit`

### Scene 8 — Evidence and close (3:12 – 3:30)

| Visual | Action |
|---|---|
| Evidence slide (section 4 table, rows animating in) → team slide → logo | Slow push-in |

**Narration:**
> "Every figure comes from committed evaluations: delay R-squared 0.87, retrieval precision 1.0, fraud recall 100%, fleet health R-squared 0.92. When the cloud fails, every agent falls back to local data. RailSense AI: grounded answers, from passenger to depot."

**Team slide (confirm names before export):**

| Module | Member |
|---|---|
| M1 Passenger Assistant | Thisarani Kawya |
| M2 Operations & Delay Prediction (team leader) | Pasindi Alawatta |
| M3 Communication Hub, Booking, Security & Fraud | Navoda Dasun |
| M4 Maintenance & Asset Intelligence | Primesh Marasingha |

---

## 6. Shot list (quick reference while recording)

| # | Window | URL | Must capture |
|---|---|---|---|
| 1 | C | `localhost:3000/user` | Hero, Delay popup, incidents map |
| 2 | C | `localhost:3000/user` hero → `localhost:5173` | Quick ask from the home page, then the signed-in assistant: Sinhala question + saved chat history in the sidebar |
| 3 | C | `/user/booking` → `/user/confirmation` | Booking steps (2×), confirmed e-ticket |
| 4 | B | `localhost:8005/` | 3D banner, prediction, incident report with train picker |
| 5 | A + C | `localhost:8005/admin`, `localhost:3000/user` | Approve → marker appears |
| 6 | B | `localhost:8005/` assistant | 🔒 Administrator-only reply |
| 7 | — | `localhost:8006/` | Health prediction, field report, flag train |
| 8 | A | `localhost:3000/admin` | Command deck, fraud queue, Hub audit |

---

## 7. Editing plan

- **Pace:** 3:30 is tight: speed up typing and form filling 2×, and cut every pause longer than 0.5 s.
- **Style:** one accent colour (RailSense gold `#C9A22A`) for captions and highlight boxes.
- **Lower-thirds:** module + technique, 2.5 s each, bottom-left.
- **Zooms:** 1.3–1.5× punch-ins on small UI (popup gauge, 🔒 reply, Approve button, map marker).
- **Cuts:** hard cuts between segments; one short cross-dissolve from the title to the architecture slide.
- **Music:** royalty-free, low-energy electronic at −24 dB under narration (e.g. YouTube Audio Library, keep the licence).
- **Subtitles:** burn in English captions from the narration and export an `.srt`.
- **Final checks:** runtime ≤ 3:40, no emails, tokens or terminals with secrets on screen, loudness about −14 LUFS.

---

## 8. If something fails during recording

| Problem | Do this |
|---|---|
| Supabase unreachable | Keep recording: screens show "Offline mode" and M2/M4 serve local data. |
| Gemini unavailable | M2's assistant shows "Rule-based fallback"; M1 falls back to fixed templates. |
| Marker doesn't appear within 5 s | Use a station with coordinates (Ella, Kandy, Galle…); other stations are counted as "unmapped". |
| A page shows old UI | Hard-refresh (Ctrl + F5). |
| Booking desk refuses the demo train | It's still flagged by M4: clear the flag on `localhost:8006`. |
| Port already in use | `.\stop_all.ps1`, then `.\start_all.ps1`. |

---

## 9. After recording

- [ ] Delete the demo incident and fraud case created for the video; clear any M4 train flag.
- [ ] Export `RailSenseAI_Project_Video.mp4` (1080p30, ~8–12 Mbps) and `RailSenseAI_Project_Video.srt`.
- [ ] Watch once on a phone and once on a laptop with sound off (captions readable?).

---

## Appendix A — Full narration script (read-through, ~450 words)

> Passengers rarely know how late their train is, or why, and staff juggle separate tools. RailSense AI brings it together: five AI agents that answer from real data, never guesses.
>
> Every agent message passes through the M3 Communication Hub, which verifies a signed token, validates and logs it. M1 serves passengers, M2 runs operations, M3 handles bookings, the Security agent scores fraud, and M4 watches the fleet, all sharing one Supabase train registry.
>
> On the passenger portal, tap Delay on any train. M2 predicts how late it will be, when it will arrive, and why, from its delay model and past incidents, in plain language. The map below shows only disruptions staff have confirmed today. Occasional travellers can ask the M1 assistant straight from the home page, no account needed. Regular passengers sign in and get the full Passenger Assistant, where every conversation is saved and can be reopened. It chats in English, Sinhala or Tamil, answers schedules and fares from its knowledge base with citations, and asks M2 through the Hub for delays.
>
> The M3 Booking Agent holds seats and calculates fares deterministically, so prices are never invented. Every booking is scored by the Security agent's IsolationForest model; suspicious ones are held for human review or rejected. Cancellations are never automatic: an administrator reviews each one.
>
> Staff work in the M2 Control Room, where Loco, our train-robot guide, reads the live data: each bar is a real corridor's average delay. In the prediction lab, M2's gradient boosting model, R-squared 0.87, predicts a delay and explains it with similar incidents found by vector search. Staff report incidents by picking the train by name; NLP classifies and summarises them. Nothing goes public until an administrator approves, and then it appears on every map within five seconds. The Operations Assistant answers only from live data and respects roles: an engineer asking for the audit log is told it's for administrators.
>
> M4 keeps the fleet safe. It scores each asset's health with per-type gradient boosting models, R-squared 0.92 on average, backed by the equipment manuals it retrieves. Passenger complaints arrive as field reports through the Hub, and when an engineer flags a train out of service, booking stops selling seats on it immediately.
>
> Administrators run everything from one portal: the command deck shows the network, today's incidents and all six agents' health, alongside the fraud and cancellation queues and a full audit trail of every Hub message.
>
> Every figure comes from committed evaluations: delay R-squared 0.87, retrieval precision 1.0, fraud recall 100%, fleet health R-squared 0.92. When the cloud fails, every agent falls back to local data. RailSense AI: grounded answers, from passenger to depot.

## Appendix B — URL and port reference

| Surface | URL |
|---|---|
| Passenger portal · booking · confirmation | `localhost:3000/user` · `/user/booking` · `/user/confirmation` |
| M1 Passenger Assistant (login, saved chat history) | `localhost:5173` · quick ask from the portal hero's **Ask AI →** |
| Unified admin portal | `localhost:3000/admin` |
| M2 Control Room · Admin Console · API docs | `localhost:8005/` · `/admin` · `/docs` |
| M4 asset dashboard · engineer chat | `localhost:8006/` · `/chat-ui` |
| Hub · Booking · Security · M1 API docs | `localhost:8002/docs` · `:8003/docs` · `:8004/docs` · `:8001/docs` |
