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
