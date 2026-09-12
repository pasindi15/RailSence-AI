# Passenger Assistant Agent — RailSense AI (Member A)

Phase 1 scaffold: chat dashboard UI + language detection + intent
classification + entity extraction + stubbed Hub routing.

## Folder structure

```
M1-passenger_assistant/
├── backend/
│   ├── main.py                # FastAPI app: /chat /feedback /health
│   ├── nlu/
│   │   ├── intent_classifier.py
│   │   ├── ner_extractor.py
│   │   └── lang_detect.py
│   ├── rag/                   # Phase 2: ChromaDB embeddings retrieval goes here
│   ├── hub_client.py          # Phase 3: real Hub wiring goes here (stub for now)
│   ├── prompts/system_prompt.md
│   ├── data/faq_docs/         # placeholder FAQ/schedule/fare docs
│   ├── tests/test_chat.py
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── src/
    │   ├── components/
    │   │   ├── Sidebar.jsx
    │   │   ├── ChatWindow.jsx
    │   │   ├── MessageBubble.jsx
    │   │   └── InputBar.jsx
    │   ├── App.jsx
    │   ├── main.jsx
    │   ├── api.js
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
cp .env.example .env            # then fill in your real Gemini key
uvicorn main:app --reload --port 8000
```

Check it's alive: open `http://localhost:8000/health`.

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
- "What time does the next train to Kandy leave?" → schedule_query
- "How much is a ticket to Galle?" → fare_query
- "Is the 14:35 Colombo Fort to Kandy train delayed?" → delay_check (stubbed Hub call)
- "The AC is broken in my compartment" → complaint (stubbed Hub call)
- "Book a second class ticket from Colombo Fort to Kandy" → booking_request (stubbed Hub call)
- Try one in Sinhala or Tamil script to confirm language detection.

### 4. Run backend tests

```bash
cd backend
pytest
```

## Phase roadmap

- **Phase 1 (this scaffold):** chat UI, intent detection, language detection,
  entity extraction, stubbed Hub calls.
- **Phase 2:** real ChromaDB RAG retrieval + citations, Supabase-backed chat
  history, sidebar loads real past sessions.
- **Phase 3:** replace `hub_client.py` stub with a real HTTP call once the
  message envelope is agreed with Member C. Wire delay_check → Operations,
  complaint → Maintenance for real.
- **Phase 4:** input sanitization hardening, multilingual accuracy testing,
  Mid-Eval / Viva demo prep.

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
