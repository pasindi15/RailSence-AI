# Passenger Assistant Agent — RailSense AI (Member A)

Chat dashboard UI + language detection + intent classification + entity
extraction, backed by Gemini and a ChromaDB RAG pipeline over the FAQ/fare/
schedule docs. Chat history and feedback persist to Supabase when configured.
Hub calls (delay_check, complaint, booking_request) are still stubbed pending
Phase 3 wiring with the real Agent Hub.

## Folder structure

```
M1-passenger_assistant/
├── backend/
│   ├── main.py                 # FastAPI app: /chat /feedback /health /chat/{id}/history
│   ├── nlu/
│   │   ├── intent_classifier.py
│   │   ├── ner_extractor.py    # regex/alias extraction + Gemini fallback for stations
│   │   └── lang_detect.py
│   ├── rag/
│   │   ├── embed_documents.py  # builds the ChromaDB "passenger_faq" collection
│   │   └── retriever.py        # top-k FAQ chunk retrieval (MiniLM embeddings)
│   ├── hub_client.py            # Phase 3 TODO: still returns stubbed Hub responses
│   ├── prompts/system_prompt.md
│   ├── data/faq_docs/           # fares.md / schedules.md / policies.md source docs
│   ├── .chroma/                 # persisted ChromaDB index (generated, gitignored)
│   ├── tests/
│   │   ├── test_chat.py
│   │   └── test_rag.py
│   ├── requirements.txt
│   └── .env                     # SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY
└── frontend/
    ├── src/
    │   ├── components/
    │   │   ├── Sidebar.jsx
    │   │   ├── ChatWindow.jsx
    │   │   ├── MessageBubble.jsx
    │   │   └── InputBar.jsx
    │   ├── App.jsx
    │   ├── main.jsx
    │   ├── api.js               # BASE_URL — must match the backend's --port
    │   └── style.css
    ├── index.html
    ├── vite.config.js
    └── package.json
```

## Step by step — run it

### 1. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create `backend/.env` with:

```
GEMINI_API_KEY=your_gemini_key
SUPABASE_URL=your_supabase_project_url
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
```

Build the RAG index (only needed once, or after editing `data/faq_docs/`):

```bash
python -m rag.embed_documents
```

Start the API. `frontend/src/api.js` currently points `BASE_URL` at port
**8010**, so run uvicorn on the same port:

```bash
uvicorn main:app --reload --port 8010
```

Check it's alive: open `http://localhost:8010/health`.

### 2. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`).

### 3. Try it

Type any of these into the chat box:
- "What time does the next train to Kandy leave?" → schedule_query (RAG-grounded answer)
- "How much is a ticket to Galle?" → fare_query (RAG-grounded answer)
- "Is the 14:35 Colombo Fort to Kandy train delayed?" → delay_check (stubbed Hub call)
- "The AC is broken in my compartment" → complaint (stubbed Hub call)
- "Book a second class ticket from Colombo Fort to Kandy" → booking_request (stubbed Hub call)
- Try one in Sinhala or Tamil script to confirm language detection and station extraction.

### 4. Run backend tests

```bash
cd backend
pytest
```

## Source of truth for passenger answers

The chatbot must never contradict the Booking Agent (M3), which owns fares, booking limits,
cancellation and refund rules. The passenger FAQ (`backend/data/faq_docs/`) is a passenger-facing
view of those rules, not a second copy that can drift:

| FAQ file | Authoritative source | How it is kept in sync |
|---|---|---|
| `fares.md` | `DEMO_FARE_RULES` in M3 `booking/fare.py` | **Generated** - `python -m rag.sync_from_m3` |
| `policies.md` (booking / cancelling / refunds / seating) | M3 `cancellation/rules.py` + `cancellation/policies/*.md` | Hand-written for passengers, **checked by** `tests/test_source_consistency.py` |
| `policies.md` (luggage, validity, complaints), `schedules.md` | M1 reference data (no other agent owns it) | Unvalidated - verify against real SLR data |

After changing any FAQ file (run from `backend/`, **with the backend venv** - the on-disk index
is not readable across chromadb versions, and `requirements.txt` pins `chromadb==1.5.9`):

```
venv\Scripts\python -m rag.sync_from_m3        # only if M3's fare table changed
venv\Scripts\python -m rag.embed_documents     # rebuild the Chroma index
venv\Scripts\python -m pytest tests            # consistency + routing + flow tests
```

Live train status comes from the Operations Agent via the Hub; its "similar past incident" and
"recorded history" text is historical and is labelled that way. Engineering manuals (M4) are
engineer-only and are never reachable from the passenger chat.

## Language: the passenger's language controls every reply

`detect_language()` runs **once** at the top of `/chat` (Sinhala `si`, Tamil `ta`, else English `en`;
mixed text goes by the script with more letters). That single `language` value is then used by every
path, and is also sent to every agent in the Hub payload (`payload.language`):

| Reply type | Who writes it, in the detected language |
|---|---|
| Fare / schedule / policy answers | **Gemini**, from the retrieved English RAG context (`_language_prompt_block`) |
| Delay, train info, train status, complaint ticket, booking-agent result (si/ta) | **Gemini**, from the agent's structured result (`present_agent_result`); guarded - the reply must be in the right script and keep the delay figure / train ID / ticket ID, else the template below is used |
| Errors, missing-station questions, cancellation cards, labels, and the fallback when Gemini is down | Fixed templates in `backend/i18n.py` (`t(key, language)`) |

English keeps its original deterministic wording for delay / train / complaint replies. The knowledge
base (`data/faq_docs/*.md`) stays English: retrieval language and answer language are independent.
To add a passenger-facing message, add it to `i18n.MESSAGES` with `en`, `si` and `ta` (a test checks
that every key has all three and the same placeholders).

## Current status

- **Working now:** language detection, intent classification, entity
  extraction (regex/alias + Gemini fallback for stations), ChromaDB RAG
  retrieval over the FAQ docs with Gemini-composed grounded replies, chat
  history persistence via Supabase, feedback endpoint.
- **Still stubbed:** `hub_client.py` — `delay_check`, `complaint`, and
  `booking_request` intents build a Hub envelope but `send_to_hub()` returns a
  hardcoded fake response instead of calling a real Hub over HTTP.

## Phase roadmap

- **Phase 1 (done):** chat UI, intent detection, language detection, entity
  extraction, stubbed Hub calls.
- **Phase 2 (done):** ChromaDB RAG retrieval + citations, Gemini-composed
  answers, Supabase-backed chat history.
- **Phase 3 (pending):** replace `hub_client.py` stub with a real HTTP call
  once the message envelope is agreed with Member C. Wire `delay_check` →
  Operations, `complaint` → Maintenance, `booking_request` → Booking for real.
- **Phase 4 (pending):** input sanitization hardening, multilingual accuracy
  testing, Mid-Eval / Viva demo prep.

## JSON contract to share with Members B, C, D now

This is the shape your `/chat` endpoint already produces internally — share it
early so they can build against it before Phase 3 wiring begins:

```json
{
  "message_id": "MSG-2001",
  "sender_agent": "passenger-agent",
  "receiver_agent": "booking-agent",
  "intent": "booking_request",
  "payload": {
    "from_station": "Colombo Fort",
    "to_station": "Kandy",
    "travel_date": "2026-12-03",
    "train_id": "PM-4082",
    "seat_class": "Second Class",
    "passenger_count": 1
  },
  "auth_token": "JWT_TOKEN",
  "timestamp": "2026-09-08T10:30:00+05:30"
}
```
