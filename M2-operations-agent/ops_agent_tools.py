"""The fixed tool set of the admin Operations Assistant.

Each tool is a thin wrapper over something M2 already serves - the Control
Room dashboard aggregate, /route-status, the delay predictor, the incident
store, the evaluation artifacts, the audit trail and the admin health check -
so the assistant reads exactly the data the screens show. A tool returns:

  {"error": ...}      the data source is unreachable ("can't reach live data")
  {"not_found": ...}  the question named something that doesn't exist
  anything else       real data, which the model may phrase

build_tools() receives the main module so the wrappers call the same
functions the HTTP endpoints do, without HTTP round-trips.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

from ops_agent import Tool


def _clock(iso: Optional[str]) -> str:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except (TypeError, ValueError):
        return "now"


def _offline_note(result: dict) -> str:
    return " _(Supabase unreachable: figures from local fallback data.)_" if result.get("offline") else ""


def _stat(label: str, value: Any, tone: str = "neutral") -> dict:
    return {"label": label, "value": str(value), "tone": tone}


def build_tools(m) -> tuple[list[Tool], Any, Any]:
    from admin import admin_db

    def known_routes() -> list[str]:
        return sorted({r.get("route") for r in m.HISTORY if r.get("route")})

    def resolve_route(text: Optional[str]) -> Optional[str]:
        """"Colombo–Badulla", "badulla line", "Colombo Fort - Badulla" -> corpus corridor."""
        if not text:
            return None
        routes = known_routes()
        norm = re.sub(r"\s*[-–—>/]+\s*|\s+to\s+", " - ", text.strip().lower())
        for r in routes:
            if r.lower() == norm:
                return r
        parts = [p.strip() for p in norm.split(" - ") if p.strip()]
        for part in reversed(parts):  # destination is the distinguishing end
            word = part.replace(" line", "").replace(" route", "").strip()
            for r in routes:
                if word and word != "colombo" and word in r.lower():
                    return r
        return None

    def data_covers() -> dict:
        dates = sorted(str(r.get("scheduled_time", ""))[:10] for r in m.HISTORY if r.get("scheduled_time"))
        return {"from": dates[0] if dates else None, "to": dates[-1] if dates else None}

    # ---------------------------------------------------------- dashboard
    def get_dashboard_kpis() -> dict:
        d = m.dashboard_data()
        o = d["overview"]
        return {
            "as_of": d["generated_at"],
            "data_source": d["data_source"]["history"],
            "offline": d["data_source"]["offline"],
            "scope": "all historical trips in the operations corpus, not only today",
            "average_delay_minutes": o["average_delay"],
            "on_time_rate_percent": o["on_time_rate"],
            "trips": o["trips"],
            "routes_monitored": o["routes_monitored"],
            "data_covers": data_covers(),
            "worst_routes": [{"route": r["route"], "average_delay_minutes": r["average_delay"],
                              "incident_rate_percent": r["incident_rate"], "status": r["status"]}
                             for r in d["routes"][:3]],
            "incident_mix": d["incident_mix"][:6],
        }

    def dashboard_template(r: dict, _a: dict) -> str:
        worst = r["worst_routes"][0] if r["worst_routes"] else None
        text = (f"Across **{r['trips']:,}** historical trips (the whole corpus, not only today), the network "
                f"averages **{r['average_delay_minutes']} min** of delay with **{r['on_time_rate_percent']}%** "
                f"of arrivals on time.")
        if worst:
            text += f" The worst corridor is **{worst['route']}** at {worst['average_delay_minutes']} min."
        return text + _offline_note(r)

    # -------------------------------------------------------------- route
    def get_route_status(route_id: str) -> dict:
        route = resolve_route(route_id)
        if route is None:
            return {"not_found": f"No corridor matches '{route_id}'.", "known_routes": known_routes()}
        status = m.route_status(route)
        rows = [r for r in m.HISTORY if r.get("route") == route]
        by_type: dict[str, list[float]] = {}
        for r in rows:
            by_type.setdefault(r.get("incident_type") or "none", []).append(float(r.get("delay_minutes") or 0))
        breakdown = sorted(
            ({"incident_type": t, "trips": len(v), "average_delay_minutes": round(sum(v) / len(v), 1)}
             for t, v in by_type.items() if t != "none"),
            key=lambda x: x["trips"], reverse=True)
        clear = by_type.get("none", [])
        dates = sorted(str(r.get("scheduled_time", ""))[:10] for r in rows if r.get("scheduled_time"))
        return {
            "route": route,
            "status": status.status,
            "average_delay_minutes": status.average_delay_minutes,
            "trips": len(rows),
            "distinct_trains": status.active_trains,
            "incident_breakdown": breakdown[:4],
            "average_delay_without_incident_minutes": round(sum(clear) / len(clear), 1) if clear else None,
            "data_covers": {"from": dates[0] if dates else None, "to": dates[-1] if dates else None},
            "note": "Historical operations corpus; there is no week-by-week live feed.",
        }

    def route_template(r: dict, _a: dict) -> str:
        if "not_found" in r:
            return f"I don't recognise that route. Known corridors: {', '.join(r['known_routes'])}."
        text = (f"**{r['route']}** is rated **{r['status']}**, averaging **{r['average_delay_minutes']} min** "
                f"of delay over {r['trips']} historical trips.")
        if r["incident_breakdown"]:
            top = r["incident_breakdown"][0]
            text += (f" Its most frequent cause is **{top['incident_type'].replace('_', ' ')}** "
                     f"({top['trips']} trips, {top['average_delay_minutes']} min average)")
            if r["average_delay_without_incident_minutes"] is not None:
                text += f", against {r['average_delay_without_incident_minutes']} min on incident-free trips"
            text += "."
        if r["data_covers"]["from"]:
            text += (f" The data covers {r['data_covers']['from']} to {r['data_covers']['to']}, "
                     "so I can't compare individual weeks.")
        return text

    # ------------------------------------------------------------ predict
    def predict_delay(route: str, train_id: str, station: Optional[str] = None,
                      scheduled_time: Optional[str] = None, weather: Optional[str] = None,
                      day_type: Optional[str] = None, incident_type: Optional[str] = None) -> dict:
        corridor = resolve_route(route)
        if corridor is None:
            return {"not_found": f"No corridor matches '{route}'.", "known_routes": known_routes()}
        try:
            req = m.DelayPredictionRequest(
                route=corridor, train_id=train_id, station=station,
                scheduled_time=scheduled_time or datetime.now(timezone.utc).isoformat(),
                weather=weather, day_type=day_type, incident_type=incident_type)
        except Exception as exc:
            return {"not_found": f"Invalid prediction input: {exc.__class__.__name__}"}
        try:
            res = m._compute_prediction(req)
        except HTTPException as exc:
            if exc.status_code >= 500:
                return {"error": "train registry unavailable", "detail": str(exc.detail)}
            return {"not_found": str(exc.detail)}
        return {
            "route": res.route, "train_id": res.train_id,
            "predicted_delay_minutes": res.predicted_delay_minutes,
            "confidence": res.confidence, "model_version": res.model_version,
            "explanation": res.explanation,
            "similar_past_incidents": res.similar_past_incidents[:2],
        }

    def predict_template(r: dict, _a: dict) -> str:
        if "not_found" in r:
            return f"I couldn't run that prediction: {r['not_found']}"
        return (f"**{r['train_id']}** on **{r['route']}** is predicted to run **{r['predicted_delay_minutes']} min** "
                f"late ({r['confidence']} confidence, model {r['model_version']}). {r['explanation']}")

    # ---------------------------------------------------------- incidents
    def get_incident_queue(status: Optional[str] = None, since: Optional[str] = None, limit: int = 8) -> dict:
        status = (status or "").strip().lower() or None
        if status == "rejected":
            return {"excluded": True,
                    "message": "Rejected incidents are not used as evidence, so the assistant does not list them."}
        res = admin_db.list_incidents(limit=200, review_status=status)
        rows = [r for r in res.get("rows", []) if str(r.get("review_status", "")).lower() != "rejected"]
        if since:
            rows = [r for r in rows if str(r.get("received_at", "")) >= since]
        items = [{
            "ref": "#" + str(r.get("incident_id", ""))[:6],
            "train_id": r.get("train_id"), "station": r.get("station"),
            "type": r.get("classified_type"), "status": r.get("review_status") or "pending",
            "summary": " ".join(str(r.get("summary") or "").split())[:140],
            "received_at": r.get("received_at"),
        } for r in rows[:max(1, min(int(limit or 8), 20))]]
        return {
            "source": res.get("source"), "offline": res.get("source") != "supabase",
            "status_filter": status, "total": len(rows),
            "counts_by_status": dict(Counter(str(r.get("review_status") or "pending") for r in rows)),
            "incidents": items,
        }

    def incidents_template(r: dict, _a: dict) -> str:
        if r.get("excluded"):
            return r["message"]
        if not r["incidents"]:
            return f"There are no {r['status_filter'] or ''} incidents in the queue.".replace("  ", " ") + _offline_note(r)
        head = (f"**{r['total']}** {r['status_filter'] or ''} incident(s) in the queue".replace("  ", " ")
                + (" (" + ", ".join(f"{v} {k}" for k, v in r["counts_by_status"].items()) + ")" if not r["status_filter"] else "")
                + ":")
        lines = [f"- {i['ref']} · {i['train_id']} at {i['station']} · {str(i['type']).replace('_', ' ')} · "
                 f"_{i['status']}_: {i['summary']}" for i in r["incidents"][:5]]
        return head + "\n" + "\n".join(lines) + _offline_note(r)

    # ------------------------------------------------------------- model
    def get_model_metrics() -> dict:
        metrics = m._metric_file(m.Path(m.__file__).parent / "evaluation" / "ml" / "delay_model_metrics.json")
        if not metrics:
            return {"not_found": "No delay_model_metrics.json - the model has not been trained yet."}
        trained = metrics.get("trained_at")
        return {
            "model": metrics.get("model"), "model_version": m.delay_model.MODEL_VERSION,
            "mae_minutes": metrics.get("mae_minutes"), "rmse_minutes": metrics.get("rmse_minutes"),
            "r2": metrics.get("r2"), "n_train": metrics.get("n_train"), "n_test": metrics.get("n_test"),
            "data_source": metrics.get("data_source"),
            "trained_at": datetime.fromtimestamp(trained, tz=timezone.utc).isoformat() if isinstance(trained, (int, float)) else trained,
            "top_features": [{"feature": f.get("feature"), "importance": round(float(f.get("importance", 0)), 4)}
                             for f in m.delay_model.get_all_features()[:5]],
        }

    def metrics_template(r: dict, _a: dict) -> str:
        if "not_found" in r:
            return r["not_found"]
        return (f"The **{r['model']}** ({r['model_version']}) scores **MAE {r['mae_minutes']} min**, "
                f"**RMSE {r['rmse_minutes']} min** and **R² {r['r2']}** on {r['n_test']} held-out trips "
                f"(trained on {r['n_train']}, {str(r['trained_at'])[:10]}). Strongest feature: "
                f"{r['top_features'][0]['feature'] if r['top_features'] else 'n/a'}.")

    # ------------------------------------------------------------- audit
    def get_audit_log(action: Optional[str] = None, agent: Optional[str] = None,
                      since: Optional[str] = None, limit: int = 8) -> dict:
        res = admin_db.list_agent_audit_events(limit=max(1, min(int(limit or 8), 25)), offset=0,
                                               agent=agent, intent=action, date_from=since)
        keep = ("timestamp", "created_at", "action", "intent", "sender_agent", "receiver_agent", "outcome")
        rows = [{k: r.get(k) for k in keep if r.get(k) is not None} for r in res.get("rows", [])]
        return {"source": res.get("source"), "offline": bool(res.get("offline")),
                "total_matching": res.get("count"), "events": rows,
                "filters": {"action": action, "agent": agent, "since": since}}

    def audit_template(r: dict, _a: dict) -> str:
        if not r["events"]:
            return "No audit events match that." + _offline_note(r)
        lines = [f"- {str(e.get('timestamp') or e.get('created_at', ''))[:16].replace('T', ' ')} · "
                 f"{e.get('intent') or e.get('action')} · {e.get('sender_agent', '?')} → {e.get('receiver_agent', '?')} · "
                 f"{e.get('outcome', '')}" for e in r["events"][:6]]
        return f"**{r['total_matching']}** matching audit events; the latest:\n" + "\n".join(lines) + _offline_note(r)

    # ------------------------------------------------------------ health
    def check_system_health() -> dict:
        from admin.admin_router import health_status
        h = health_status(identity={})
        return {
            "supabase": h["supabase"], "hub": h["hub"], "upstash": h["upstash"],
            "llm": {"gemini_configured": bool(m.os.getenv("GEMINI_API_KEY"))},
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def health_template(r: dict, _a: dict) -> str:
        sb, hub, up = r["supabase"], r["hub"], r["upstash"]
        parts = [
            "Supabase is **reachable**." if sb["reachable"] else
            ("Supabase is **unreachable**; M2 is serving local fallback data." if sb["configured"] else "Supabase is **not configured**."),
            f"The agent Hub ({hub['base_url']}) is **{'reachable' if hub['reachable'] else 'unreachable'}**.",
            "Upstash is **configured**." if up["configured"] else "Upstash is **not configured** (no UPSTASH_REDIS_URL/TOKEN).",
        ]
        return " ".join(parts)

    # ---------------------------------------------------------- registry
    str_prop = lambda d: {"type": "string", "description": d}  # noqa: E731
    tools = [
        Tool("get_dashboard_kpis",
             "Network-wide delay KPIs from the Control Room dashboard: average delay, on-time rate, trip count, "
             "worst routes and incident mix. Covers the whole historical corpus.",
             {"type": "object", "properties": {}},
             get_dashboard_kpis,
             lambda r, a: f"Dashboard KPIs as of {_clock(r['as_of'])} ({r['data_source']})",
             lambda r: [_stat("Avg delay", f"{r['average_delay_minutes']} min"),
                        _stat("On time", f"{r['on_time_rate_percent']}%"),
                        _stat("Trips", f"{r['trips']:,}")],
             dashboard_template,
             permission="m2.control_room.view", capability="network delay KPIs",
             examples=("What's the network average delay?", "Which route has the worst delays?")),
        Tool("get_route_status",
             "Status, average delay and incident breakdown for one corridor, e.g. 'Colombo Fort - Badulla'. "
             "Use for questions about a specific route or why a route performs badly.",
             {"type": "object", "properties": {"route_id": str_prop("Route or destination, e.g. 'Colombo - Badulla' or 'Badulla'")},
              "required": ["route_id"]},
             get_route_status,
             lambda r, a: f"Route status: {r['route']} ({r['trips']} trips)" if "route" in r else f"Route lookup: {a.get('route_id')} not found",
             lambda r: [] if "not_found" in r else [
                 _stat("Avg delay", f"{r['average_delay_minutes']} min"),
                 _stat("Posture", r["status"], "bad" if r["status"] == "critical" else "warn" if r["status"] == "watch" else "good")],
             route_template,
             permission="m2.control_room.view", capability="route status and delay causes",
             examples=("Why is Colombo – Badulla worse this week?",)),
        Tool("predict_delay",
             "Predict the delay for a train on a route with the trained delay model (no alerts are sent).",
             {"type": "object", "properties": {
                 "route": str_prop("Route, e.g. 'Colombo Fort - Kandy'"),
                 "train_id": str_prop("Train id, e.g. 'PM-4082' or '1005'"),
                 "station": str_prop("Optional station"),
                 "scheduled_time": str_prop("Optional ISO 8601 time; defaults to now"),
                 "weather": {"type": "string", "enum": ["clear", "light_rain", "heavy_rain", "fog", "extreme_heat"]},
                 "day_type": {"type": "string", "enum": ["weekday", "weekend", "public_holiday"]},
                 "incident_type": {"type": "string", "enum": ["none", "signal_fault", "mechanical", "weather", "track_obstruction", "staffing"]},
             }, "required": ["route", "train_id"]},
             predict_delay,
             lambda r, a: (f"Delay model {r['model_version']}: {r['train_id']} on {r['route']}"
                           if "model_version" in r else f"Prediction for {a.get('train_id')}: not run"),
             lambda r: [] if "not_found" in r else [
                 _stat("Predicted", f"{r['predicted_delay_minutes']} min"),
                 _stat("Confidence", r["confidence"])],
             predict_template,
             permission="m2.prediction.run", capability="delay predictions for a train",
             examples=("Predict the delay for PM-4082 on the Kandy line",)),
        Tool("get_incident_queue",
             "Incident reports in the review queue, optionally filtered by status "
             "(pending, corrected, approved, verified). Rejected incidents are never returned.",
             {"type": "object", "properties": {
                 "status": {"type": "string", "enum": ["pending", "corrected", "approved", "verified", "rejected"]},
                 "since": str_prop("Optional ISO date; only incidents received on/after it"),
                 "limit": {"type": "integer", "description": "Max incidents to list (default 8)"},
             }},
             get_incident_queue,
             lambda r, a: ("Incidents " + ", ".join(i["ref"] for i in r["incidents"][:4])
                           if r.get("incidents") else "Incident queue: none matching"),
             lambda r: [] if r.get("excluded") else [
                 _stat(k.capitalize(), v, "warn" if k == "pending" else "good" if k == "verified" else "neutral")
                 for k, v in r["counts_by_status"].items()],
             incidents_template,
             permission="m2.control_room.view", capability="the incident review queue",
             examples=("Any pending incidents?",)),
        Tool("get_model_metrics",
             "Held-out metrics of the delay model's last training run: MAE, RMSE, R², sizes, date, version, top features.",
             {"type": "object", "properties": {}},
             get_model_metrics,
             lambda r, a: (f"Model metrics: {r['model_version']}, trained {str(r['trained_at'])[:10]}"
                           if "model_version" in r else "Model metrics: not available"),
             lambda r: [] if "not_found" in r else [
                 _stat("MAE", f"{r['mae_minutes']} min"), _stat("RMSE", f"{r['rmse_minutes']} min"), _stat("R²", r["r2"])],
             metrics_template,
             permission="m2.model.manage", capability="delay-model metrics",
             topic="Delay-model metrics and training",
             examples=("How accurate is the delay model?",)),
        Tool("get_audit_log",
             "Recent entries of the inter-agent audit trail, optionally filtered by action/intent, agent, or since date.",
             {"type": "object", "properties": {
                 "action": str_prop("Action or intent, e.g. 'prediction', 'incident_approve', 'ops_agent_query'"),
                 "agent": str_prop("Sender or receiver agent name"),
                 "since": str_prop("Optional ISO date lower bound"),
                 "limit": {"type": "integer", "description": "Max events (default 8)"},
             }},
             get_audit_log,
             lambda r, a: f"Audit log: {r['total_matching']} events ({r['source']})",
             lambda r: [_stat("Events", r["total_matching"])],
             audit_template,
             permission="m2.audit.view", capability="the audit log", topic="The audit log",
             examples=("What were the last 3 audit events?",)),
        Tool("check_system_health",
             "Connectivity of Supabase, the agent Hub and Upstash, plus whether the LLM is configured.",
             {"type": "object", "properties": {}},
             check_system_health,
             lambda r, a: f"System health check at {_clock(r['checked_at'])}",
             lambda r: [_stat("Supabase", "up" if r["supabase"]["reachable"] else "down", "good" if r["supabase"]["reachable"] else "bad"),
                        _stat("Hub", "up" if r["hub"]["reachable"] else "down", "good" if r["hub"]["reachable"] else "bad"),
                        _stat("Upstash", "configured" if r["upstash"]["configured"] else "not set",
                              "good" if r["upstash"]["configured"] else "warn")],
             health_template,
             permission="m2.system.config", capability="system health",
             topic="System health (Supabase, Hub and Upstash)",
             examples=("Is the Hub online?",)),
    ]
    return tools, known_routes, data_covers
