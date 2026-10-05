# Passenger Assistant Agent — RailSense AI (Member A)

Chat dashboard UI + language detection + intent classification + entity
extraction, backed by Gemini/OpenRouter and a ChromaDB RAG pipeline over the
FAQ/fare/schedule docs. Chat history and feedback persist to Supabase when
configured. Hub calls (`delay_check` → Operations, `complaint` → Maintenance,
`booking_request`/`cancel_booking` → Booking) are wired to the real Agent Hub
over HTTP, with a local mock fallback (`USE_MOCK_HUB=true`) for dev without
the Hub running.

Two passenger-facing features worth knowing about before touching the NLU
layer:
- **Romanized Sinhala ("Singlish") support** — a passenger typing Sinhala in
  Latin letters (`"mata colomba idala badullata ticket ekak ganna oni"`, or
  even heavily abbreviated txt-speak like `"ek kiyd"`) is detected as Sinhala
  and answered in Sinhala script. See `backend/nlu/romanized.py` and
  `evaluation/romanized_sinhala/`.
- **Session-sticky conversation language** — the language detected from a
  session's first meaningful message is persisted and reused for every
  follow-up in that session (a bare `"3"` answering "how many passengers?"
  doesn't flip the reply back to English). See `resolve_session_language()`
  in `backend/main.py`.

## Folder structure

```
M1-passenger_assistant/
├── backend/
│   ├── main.py                 # FastAPI app: /chat /chat/quick /feedback /health /chat/{id}/history
│   ├── auth.py                  # passenger JWT auth (bcrypt + short-lived JWTs), guards chat ownership
│   ├── llm_client.py            # Gemini or OpenRouter, chosen by LLM_PROVIDER — same generate_content() surface either way
│   ├── hub_client.py             # real HTTP calls to the Agent Hub; USE_MOCK_HUB=true for local dev without it
│   ├── i18n.py                   # en/si/ta message catalog for every fixed (non-Gemini) passenger-facing string
│   ├── supabase_schema.sql       # chat_sessions / chat_messages schema, incl. the sticky-language column
│   ├── nlu/
│   │   ├── intent_classifier.py
│   │   ├── ner_extractor.py    # regex/alias extraction + Gemini fallback for stations
│   │   ├── lang_detect.py      # si/ta/en detection: Unicode script → romanized-Sinhala lexicon → langdetect fallback
│   │   └── romanized.py        # romanized Sinhala ("Singlish") detection, intent keywords, station aliases
│   ├── rag/
│   │   ├── embed_documents.py  # builds the ChromaDB "passenger_faq" collection
│   │   ├── retriever.py        # top-k FAQ chunk retrieval (MiniLM embeddings)
│   │   └── sync_from_m3.py     # regenerates fares.md from M3's DEMO_FARE_RULES
│   ├── prompts/system_prompt.md
│   ├── data/faq_docs/           # fares.md / schedules.md / policies.md source docs
│   ├── .chroma/                 # persisted ChromaDB index (generated, gitignored)
│   ├── tests/                    # ~14 files — chat flow, ownership, RAG, routing, romanized Sinhala,
│   │   │                         # conversation language/context, multilingual + language-consistency, Hub client
│   │   └── ...
│   ├── requirements.txt
│   └── .env                     # SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, OPENROUTER_API_KEY / GEMINI key, JWT_SECRET_KEY, AGENT_HUB_URL
├── evaluation/
│   ├── romanized_sinhala/        # offline NLU accuracy eval (no server/LLM) — run_eval.py, queries.csv, results.md
│   └── prompt_injection/         # PI/jailbreak security assessment — test plan, run_pi_tests.py, evidence/*.json
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
OPENROUTER_API_KEY=your_openrouter_key
# optional: OPENROUTER_MODEL=google/gemma-4-31b-it:free
SUPABASE_URL=your_supabase_project_url
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
```

Build the RAG index (only needed once, or after editing `data/faq_docs/`):

```bash
python -m rag.embed_documents
```

Start the API on port **8010** for standalone backend dev (match whatever
`VITE_M1_URL`/gateway config the frontend is using). When launched as part of
the full system via the repo root's `start_all.ps1` / `start.py`, M1 instead
runs on whatever `railsense_ports.json` assigns it (currently **8001**) —
check that file rather than assuming a port. Always launch uvicorn through
the venv's own Python directly - don't rely on `uvicorn` being on PATH / the
venv being activated.
If a global Python is ever picked up instead, the `.chroma` index (built with
`chromadb==1.5.9`) becomes unreadable and every RAG query silently falls back
to "I'm having trouble looking that up right now" (`KeyError: '_type'`):

```bash
venv\Scripts\python.exe -m uvicorn main:app --reload --port 8010
```

or just run `run.bat` / `.\run.ps1` from `backend/`, which do the same thing.

Check it's alive: open `http://localhost:8010/health`. The startup log prints
the Python executable and chromadb version in use - confirm it points at
`backend\venv\Scripts\python.exe` and chromadb `1.5.9`.

### 2. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173/user/chat/` for dev. In the full system, run `npm run build` here; the gateway then serves the app at `http://localhost:3000/user/chat/`.

### 3. Try it

Type any of these into the chat box:
- "What time does the next train to Kandy leave?" → schedule_query (RAG-grounded answer)
- "How much is a ticket to Galle?" → fare_query (RAG-grounded answer)
- "Is the 14:35 Colombo Fort to Kandy train delayed?" → delay_check (real Hub call to Operations)
- "The AC is broken in my compartment" → complaint (real Hub call to Maintenance)
- "Book a second class ticket from Colombo Fort to Kandy" → booking_request (real Hub call to Booking)
- Try one in Sinhala or Tamil script (or romanized Sinhala, e.g. "mata colomba idala badullata ticket ekak ganna oni") to confirm language detection and station extraction.
- Ask a follow-up with just a number ("3") after a fare question — the reply should stay in whatever language the first question was in.

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

`resolve_session_language(session_id, text)` decides the language for every `/chat` turn (Sinhala
`si`, Tamil `ta`, else English `en`). It is **not** per-message detection: once a session's first
meaningful message establishes a language, every later turn in that session reuses the *stored*
language regardless of what script/words that later message itself contains — so a bare `"3"`
answering "how many passengers?" in a Sinhala session stays Sinhala. `detect_language()` only runs
to establish the language on a session's first turn (or if the passenger explicitly asks to switch,
e.g. "in Tamil please" / "தமிழில் பதில் சொல்லுங்கள்" — matched by name, in any of the three scripts).
For real (non-Choo) sessions this is persisted in `chat_sessions.language` in Supabase (see
`supabase_schema.sql`) and restored automatically whenever that session is reopened; Choo
(`/chat/quick`) keeps the same per-session stickiness in-process instead, since it never writes to
Supabase. `detect_language()` itself goes Unicode script → romanized-Sinhala lexicon
(`nlu/romanized.py`) → `langdetect` fallback; mixed script text goes by whichever script has more
letters. The resolved `language` value is then used by every downstream path, and is also sent to
every agent in the Hub payload (`payload.language`):

| Reply type | Who writes it, in the detected language |
|---|---|
| Fare / schedule / policy answers | **Gemini**, from the retrieved English RAG context (`_language_prompt_block`) |
| Delay, train info, train status, complaint ticket, booking-agent result (si/ta) | **Gemini**, from the agent's structured result (`present_agent_result`); guarded - the reply must be in the right script and keep the delay figure / train ID / ticket ID, else the template below is used |
| Errors, missing-station questions, cancellation cards, labels, and the fallback when Gemini is down | Fixed templates in `backend/i18n.py` (`t(key, language)`) |

English keeps its original deterministic wording for delay / train / complaint replies. The knowledge
base (`data/faq_docs/*.md`) stays English: retrieval language and answer language are independent.
To add a passenger-facing message, add it to `i18n.MESSAGES` with `en`, `si` and `ta` (a test checks
that every key has all three and the same placeholders).

## Romanized Sinhala ("Singlish") support

A passenger typing Sinhala in Latin letters — `"mata colomba idala badullata ticket ekak ganna oni"`
— is detected as `si` and answered in Sinhala script, not English. `nlu/romanized.py` handles this in
three parts: `is_romanized_sinhala()` (language detection — a Sinhala-only domain word like
`"kochchiya"` trusts a single hit, grammar/function words need two hits or a high ratio of the
message), `match_intent()` / `match_stations()` (a parallel romanized lexicon + station-alias table,
with a fuzzy fallback for misspellings like `"kolombo"`). Casual vowel-dropped txt-speak
(`"kiyd"` for `"kiyada"`, `"clmbo"` for `"colombo"`, `"indn"` for `"indan"`) is tolerated via a
`SequenceMatcher`-based fuzzy match against the function-word lexicon only — deliberately **not**
against the single-hit-trust domain-word list, because that fuzzy-matches plain English place names
(`"colombo"` → `"colomba"`) closely enough to misfire. `evaluation/romanized_sinhala/run_eval.py` is
an offline, server-free accuracy check over 56 queries (`queries.csv`) — currently 100% on language
detection, intent classification, and both station roles; re-run it after any change to
`nlu/romanized.py` or `nlu/lang_detect.py`.

## Security evaluation: prompt injection / jailbreak resistance

`evaluation/prompt_injection/` holds a 15-case adversarial test plan
(`PI_Jailbreak_Vulnerability_Assessment_TestPlan.md`) covering system-prompt extraction, persona
jailbreaks, policy/authority spoofing, Base64 obfuscation, grounding/hallucination induction,
cross-passenger data access, agentic abuse of the booking/cancellation actions, a Sinhala-language
guardrail-bypass attempt, Hub command injection, and multi-turn context poisoning. `run_pi_tests.py`
executes all 15 against the live `/chat` endpoint and saves the complete raw JSON for each to
`evidence/PI-XX.json` (no retries, no cherry-picking — first attempt is the record).

Latest run (2026-10-01): **13/15 PASS**. Neither of the 2 FAILs is an actual injection or jailbreak
success — no system prompt, grounding rule, or other passenger's data was ever disclosed in any
case. They're a missing-refusal gap (a "list another passenger's bookings" request got misrouted
into the booking flow instead of being refused) and a RAG retrieval miss on one Sinhala-language
query (it correctly declined to invent a fare rather than hallucinating one, but didn't retrieve the
real fare either). Both are written up as DRAFT findings in the test plan's `Vulnerability findings`
section, pending TK's review before being treated as closed.

## Current status

- **Working now:** language detection (including romanized Sinhala and
  session-sticky conversation language), intent classification, entity
  extraction (regex/alias + Gemini fallback for stations), ChromaDB RAG
  retrieval over the FAQ docs with Gemini-composed grounded replies, chat
  history persistence + ownership via Supabase + JWT auth, feedback endpoint,
  real Hub calls for `delay_check` (Operations), `complaint` (Maintenance),
  and `booking_request`/`cancel_booking` (Booking), with `USE_MOCK_HUB=true`
  as a local-dev fallback when the Hub isn't running.
- **Known gaps (see Vulnerability findings, both low-severity):** a
  natural-language "list another passenger's data" request isn't explicitly
  refused (no data leaks, but it should redirect instead of falling into the
  booking flow); RAG retrieval is less reliable on at least one tested
  Sinhala-language query shape.

## Phase roadmap

- **Phase 1 (done):** chat UI, intent detection, language detection, entity
  extraction, stubbed Hub calls.
- **Phase 2 (done):** ChromaDB RAG retrieval + citations, Gemini-composed
  answers, Supabase-backed chat history.
- **Phase 3 (done):** `hub_client.py` makes real HTTP calls to the Agent Hub.
  `delay_check` → Operations, `complaint` → Maintenance, `booking_request` /
  `cancel_booking` → Booking are all wired for real, not stubbed.
- **Phase 4 (in progress):** romanized Sinhala support, session-sticky
  conversation language, and a 15-case prompt-injection/jailbreak assessment
  are done (see sections above); multilingual accuracy testing and remaining
  input-sanitization hardening (the 2 open low-severity findings) continue
  ahead of Mid-Eval / Viva demo prep.

## JSON contract to share with Members B, C, D

This is the shape M1 actually sends in the Hub envelope now that Phase 3 wiring
is live — the reference for anyone building against it:

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
