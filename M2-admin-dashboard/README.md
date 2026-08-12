# M2 Admin Dashboard

A fully operational admin panel for the Operations & Delay-Prediction Agent,
with a home page and six dashboards: **Data Management**, **Incident Review
Queue**, **System Health & Config**, **Model Operations**, **Hub & Event
Control**, and **Audit & Access Control**.

This package is now integrated into the runnable `M2-operations-agent` service.
It is available at `http://localhost:8001/admin/` and does not replace the
operator console at `/`.

---

## 1. Existing integration layout

Copy this package's contents into your `M2-operations-agent/` folder like so:

```
M2-operations-agent/
├── main.py                     <- yours, unchanged except 2 new lines (see step 3)
├── admin/                      <- NEW: copy backend/ here, rename to admin/
│   ├── __init__.py
│   ├── admin_db.py
│   ├── admin_auth.py
│   ├── admin_router.py
│   └── admin_schema.sql
├── admin_ui/                   <- NEW: copy ui/admin/ contents here
│   ├── index.html
│   ├── css/admin.css
│   └── js/...
├── ml/                          <- yours, unchanged
├── data/                        <- yours, unchanged
└── ... (everything else unchanged)
```

The integration copies this package into the service as:

```bash
cp -r backend/*  M2-operations-agent/admin/
cp -r ui/admin/*  M2-operations-agent/admin_ui/
```

(On Windows PowerShell: `Copy-Item -Recurse backend\* ..\M2-operations-agent\admin\`
and similarly for the UI folder — create the destination folders first.)

## 2. Install the one extra dependency

```bash
pip install -r requirements-admin.txt
```

(Just `python-multipart` — needed for the CSV import endpoint.)

## 3. FastAPI wiring

```python
from fastapi.staticfiles import StaticFiles
from admin.admin_router import router as admin_router

app.include_router(admin_router)
app.mount("/admin", StaticFiles(directory="admin_ui", html=True), name="admin_ui")
```

The current `main.py` already includes the router and mounts the static UI at
`/admin`; `/admin/*` remains a separate namespace from `/predict-delay` and
`/incident-report`.

## 4. Run the SQL

In the Supabase SQL editor, run `admin/admin_schema.sql`. It only creates
**new** tables (`incident_reports`, `model_training_runs`, `admin_config`,
`admin_users`) — it does not touch `operations_history`, `audit_events`,
`operational_events`, or `incident_embeddings`.

## 5. Set admin credentials

Add to your repo-root `.env`:

```
ADMIN_USERNAME=admin
ADMIN_PASSWORD=choose-a-real-password
ADMIN_TOKEN_SECRET=any-long-random-string
```

If you skip this, it falls back to `admin` / `operations2026` — change this
before your demo or viva.

## 6. Run it

```bash
python -m uvicorn main:app --app-dir M2-operations-agent --reload --port 8001
```

Open **`http://localhost:8001/admin/`** and log in. The default development
credentials are `admin` / `operations2026`; configure `ADMIN_USERNAME` and
`ADMIN_PASSWORD` before a real demo.

---

## What's real vs. what's a placeholder

| Feature | Status |
|---|---|
| Data Management CRUD, CSV import, quality check | Fully functional against `operations_history` (Supabase) with a read-only CSV fallback |
| System Health & Config | Fully functional — live-probes Supabase, Hub, and reads env presence |
| Model retrain / rollback | Fully functional — actually runs `ml/train_delay_model.py` as a subprocess and backs up `.pkl` files before overwriting |
| Hub status / events / test alert | Fully functional — calls your real `HUB_BASE_URL` and Upstash REST API if configured |
| Incident Review Queue | Fully functional, but starts **empty** until you wire one insert (see below) |
| Audit & Access Control | Fully functional against `audit_events`, with the same JSONL fallback pattern as your dashboard |
| Admin login | **Placeholder.** Simple env-var username/password with a signed token — see `admin/admin_auth.py`. Swap for the Security Agent's real JWT system before final submission so there's one source of truth for auth. |

## Wiring the Incident Review Queue to real submissions (optional, 5 lines)

Your existing `POST /incident-report` handler already computes `summary` and
`classified_type`. To make new submissions show up in the review queue, add
this after that computation in `main.py`:

```python
from admin import admin_db
admin_db.insert_row("incident_reports", {
    "train_id": payload.train_id,
    "station": payload.station,
    "raw_text": payload.text,
    "summary": summary,
    "classified_type": classified_type,
    "nlp_method": nlp_method,
})
```

Wrap it in a `try/except: pass` if you want it to be fully best-effort, in
keeping with the rest of your graceful-degradation pattern.

## Notes

- All admin routes require a valid admin token — none of this is exposed to
  passenger-facing traffic or the public dashboard.
- The retrain endpoint actually re-runs your training script, so use it
  deliberately (it will take as long as `train_delay_model.py` normally
  does) — great for a live viva demo of "the model can be retrained on
  demand," not something to click repeatedly during testing.
- Everything degrades the same way your existing dashboard does: if
  Supabase isn't configured, you'll see clear "unavailable" / fallback
  labels rather than the UI silently breaking.
