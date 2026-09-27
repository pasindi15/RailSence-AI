"""Operations Assistant: a role-aware, tool-calling agent over M2's own data.

Used by administrators and operations engineers from the Admin Console and
the Control Room. The model never answers from its own knowledge. It may only
choose among the fixed tools registered by main.py - and only the ones the
user's role is allowed to use (each tool carries the same RBAC capability as
the screen it mirrors). The backend runs the tool against real data and the
model phrases the answer from the returned JSON.

When a question cannot be answered, the model does not improvise a refusal.
It calls one of three signal tools (report_restricted / report_insufficient /
report_out_of_scope) and the backend replies with a fixed, properly worded
message. Every response carries an `answer_type`:

  answer             grounded answer from tool results
  restricted         the topic is reserved for administrators
  insufficient_data  operations question, but details are missing, the thing
                     asked about doesn't exist, or it asks for an action
  out_of_scope       not about railway operations
  unavailable        the data source could not be reached

Safeguards against invented content:
1. Number guard - every number in the model's answer must appear in the tool
   results (or the question); otherwise a template built from the same
   results is used instead.
2. Free text produced without any tool call is never shown.
3. Rule-based fallback when Gemini is missing or failing.
4. `highlights` (stat chips) and `sources` (citations) are built by code.

History (ops_agent_queries) is stored per user in Supabase with a local JSONL
mirror, following the incident store's fallback pattern.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("railsense.ops_agent")

MAX_TOOL_ROUNDS = 4
LLM_TIMEOUT_SECONDS = 25

ROLE_LABELS = {"admin": "Administrator", "operations_engineer": "Operations Engineer"}

# Things the assistant can never do for anyone: no tool performs actions.
ACTION_WORDS = ("officer", "password", "user account", "deactivate", "reactivate", "create user",
                "add user", "delete user", "change role", "change my role", "assign role",
                "retrain", "rollback", "roll back", "approve incident", "reject incident")
ACTION_TOPIC = "Officer, role and password management, model retraining and incident approval"
ACTION_TOPICS = (
    (("officer", "password", "account", "user", "role", "permission", "activate"), "Officer, role and password management"),
    (("retrain", "rollback", "roll back", "training"), "Model retraining and rollback"),
    (("approv", "reject"), "Incident approval"),
)
DATE_WORDS = ("date", "day", "month", "period", "data_covers", "specific", "week", "year")

SYSTEM_PROMPT_TEMPLATE = """You are the RailSense Operations Assistant. The signed-in user is a {role_label}.

Rules you must follow:
- Every factual answer MUST come from a tool call. Never answer from your own knowledge.
- Never invent, estimate, round differently or extrapolate numbers, ids, names or dates.
  Copy figures exactly as the tools return them.
- If a tool result has "offline": true or "stale": true, say the figures come from local
  fallback data. If a tool returns an "error", say you can't reach live data right now.
- Dashboard averages cover the whole historical operations corpus, not just today; say so
  when the user asks about "today" or "this week".
- The tools cannot filter by a specific date, day or month. If the user asks for figures on a
  specific date or month (e.g. "on 3rd March", "in June"), call report_insufficient and explain
  that the data is only available for the whole period in data_covers.
- Rejected incidents are never evidence; the incident tool already excludes them.
{restricted_rule}- If the question is about railway operations but the tools cannot answer it (required details
  are missing - a delay prediction needs a train AND a route - or it asks you to perform an action
  such as managing officers, roles or passwords, retraining or rolling back the model, approving or
  rejecting incidents), call report_insufficient. Do not guess and do not ask in free text.
- If the question is not about railway operations at all, call report_out_of_scope.
- Be concise: 1-4 short sentences, or a short list using "- " bullets. Use **bold** for key figures.
"""

# Signals the model calls instead of writing its own refusal; the backend
# turns each into a fixed, properly worded message.
SIGNAL_TOOLS = {
    "report_restricted": {
        "description": "Call when the user asks about something reserved for administrators "
                       "(listed in your instructions). Do not answer it.",
        "parameters": {"type": "object", "properties": {
            "topic": {"type": "string", "description": "Which restricted topic was asked about"}}},
    },
    "report_insufficient": {
        "description": "Call when the question is about railway operations but cannot be answered: "
                       "required details are missing, or it asks for an action the assistant cannot perform.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string", "description": "Short plain reason, no numbers"},
            "missing": {"type": "string", "description": "Only details the user could type in to make it "
                        "answerable (e.g. 'the train and the route'); leave empty for actions or data gaps"}}},
    },
    "report_out_of_scope": {
        "description": "Call when the question is not about railway operations at all.",
        "parameters": {"type": "object", "properties": {}},
    },
}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[..., dict]
    source_label: Callable[[dict, dict], str]
    highlights: Callable[[dict], list[dict]]
    template: Callable[[dict, dict], str]
    # RBAC capability required to use the tool (the same as the screen it mirrors).
    permission: str = "m2.control_room.view"
    capability: str = ""      # "network delay KPIs", used in help messages
    topic: str = ""           # "The audit log", used in restricted messages
    examples: tuple = ()      # example questions shown in the widget


# ------------------------------------------------------------------ guard

_NUM_RE = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)*(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    out = []
    for raw in _NUM_RE.findall(text or ""):
        try:
            out.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return out


def _allowed_numbers(results: list[dict], question: str) -> set[float]:
    allowed: set[float] = set()
    blob = json.dumps(results, default=str)
    for n in _numbers(blob) + _numbers(question):
        allowed.update({n, round(n), round(n, 1), round(n, 2)})
        if abs(n) <= 1:  # ratios such as r2 = 0.8551 quoted as 85.5 %
            allowed.update({round(n * 100), round(n * 100, 1), round(n * 100, 2)})

    def walk(v):
        if isinstance(v, list):
            allowed.add(float(len(v)))
            for i in v:
                walk(i)
        elif isinstance(v, dict):
            for i in v.values():
                walk(i)
    walk(results)
    return allowed


def numbers_grounded(answer: str, results: list[dict], question: str) -> tuple[bool, list[float]]:
    allowed = _allowed_numbers(results, question)
    unsupported = [n for n in _numbers(answer)
                   if n not in allowed and round(n, 1) not in allowed and round(n) not in allowed]
    return (not unsupported, unsupported)


_TOPIC_KEYWORDS = (
    (("audit", "log", "event", "activity"), "get_audit_log"),
    (("health", "hub", "supabase", "upstash", "connect", "online", "system"), "check_system_health"),
    (("model", "mae", "rmse", "accuracy", "metric", "feature", "training"), "get_model_metrics"),
)


def _clean_phrase(text: Optional[str], limit: int = 160) -> str:
    """Model-supplied reason text: plain, short, and never carrying figures."""
    t = " ".join(str(text or "").split())[:limit].strip().rstrip(".")
    return "" if not t or re.search(r"\d", t) else t


# ------------------------------------------------------------ fallback router

def route_question(question: str, known_routes: list[str]) -> list[tuple[str, dict]]:
    """Keyword router used when the LLM is unavailable. Returns tool calls."""
    q = question.lower()
    calls: list[tuple[str, dict]] = []

    def has(*words):
        return any(w in q for w in words)

    route = next((r for r in known_routes
                  if r.lower().split(" - ")[-1] in q), None)
    train = re.search(r"\b([a-z]{2,4}-\d{2,5}|\d{2,5})\b", q)

    if has("health", "supabase", "hub", "upstash", "online", "offline", "reachable", "system status", "connectivity"):
        calls.append(("check_system_health", {}))
    if has("incident", "queue", "pending", "verified", "approval", "report"):
        status = next((s for s in ("pending", "verified", "corrected", "approved", "rejected") if s in q), None)
        calls.append(("get_incident_queue", {"status": status} if status else {}))
    if has("model", "mae", "rmse", "r2", "r²", "accuracy", "metric", "trained", "feature"):
        calls.append(("get_model_metrics", {}))
    if has("audit", "event", "activity", "who approved", "who rejected", "who changed", "who filed"):
        calls.append(("get_audit_log", {}))
    if train and has("predict", "delay", "late", "will ") and route:
        calls.append(("predict_delay", {"route": route, "train_id": train.group(1).upper()}))
    elif route and has("route", "line", "worse", "why", "status", "corridor", "delay", "incident"):
        calls.append(("get_route_status", {"route_id": route}))
    if not calls and has("average", "delay", "kpi", "on-time", "on time", "punctual", "network",
                         "overview", "today", "trips", "worst", "route"):
        calls.append(("get_dashboard_kpis", {}))
    return calls


# ------------------------------------------------------------------ agent

class OpsAgent:
    def __init__(self, tools: list[Tool], known_routes: Callable[[], list[str]],
                 coverage: Optional[Callable[[], dict]] = None):
        self.tools = {t.name: t for t in tools}
        self.known_routes = known_routes
        self.coverage = coverage  # {"from": "2025-01-01", "to": "2025-07-30"} of the corpus

    # -- role helpers ----------------------------------------------------
    def allowed_tools(self, permissions: set[str]) -> list[str]:
        return [n for n, t in self.tools.items() if t.permission in permissions]

    def capabilities(self, permissions: set[str]) -> dict:
        allowed = self.allowed_tools(permissions)
        return {
            "tools": allowed,
            "can_help_with": [self.tools[n].capability for n in allowed if self.tools[n].capability],
            "restricted_topics": [t.topic for n, t in self.tools.items() if n not in allowed and t.topic],
            "examples": [q for n in allowed for q in self.tools[n].examples][:6],
        }

    def _caps_text(self, allowed: list[str]) -> str:
        caps = [self.tools[n].capability for n in allowed if self.tools[n].capability]
        if len(caps) > 1:
            return ", ".join(caps[:-1]) + " and " + caps[-1]
        return caps[0] if caps else "RailSense operations data"

    def _canonical_topic(self, topic: str) -> str:
        """Map the model's wording ("audit log", "officer account creation") to one fixed name."""
        t = (topic or "").lower()
        for words, name in ACTION_TOPICS:
            if any(w in t for w in words):
                return name
        for words, tool in _TOPIC_KEYWORDS:
            if any(w in t for w in words) and self.tools.get(tool) and self.tools[tool].topic:
                return self.tools[tool].topic
        return (topic[0].upper() + topic[1:]) if topic else ""

    # -- fixed messages --------------------------------------------------
    def _message(self, kind: str, allowed: list[str], role: str, topic: str = "",
                 reason: str = "", missing: str = "") -> str:
        caps = self._caps_text(allowed)
        if kind == "restricted":
            return (f"🔒 **{topic or 'That information'}** is only available to administrators, so I can't "
                    f"share it with your {ROLE_LABELS.get(role, role)} account.\n\n"
                    f"I can help you with {caps}. If you need this, please ask an administrator.")
        if kind == "insufficient_data":
            text = "I don't have enough information to answer that."
            if reason:
                text += f" {reason[0].upper() + reason[1:]}."
            if missing:
                text += f" Please tell me {missing[0].lower() + missing[1:]}."
            return text + f"\n\nI can help you with {caps}."
        if kind == "unavailable":
            return ("I can't reach the live operations data right now, so I won't guess an answer. "
                    "Please try again in a moment.")
        return ("That's outside what I can help with: I only answer questions about RailSense "
                f"operations, using live M2 data.\n\nYou can ask me about {caps}.")

    # -- tool execution --------------------------------------------------
    def _execute(self, name: str, args: dict, trace: list[dict], allowed: list[str]) -> dict:
        tool = self.tools.get(name)
        if tool is None:
            result = {"error": f"unknown tool {name}"}
        elif name not in allowed:  # defence in depth: never run a tool the role lacks
            result = {"forbidden": True}
        else:
            try:
                result = tool.run(**(args or {}))
            except TypeError as exc:
                result = {"error": f"bad arguments: {exc}"}
            except Exception as exc:  # a tool failure must not become an invented answer
                logger.warning("ops agent tool %s failed: %s", name, exc)
                result = {"error": "live data unavailable", "detail": exc.__class__.__name__}
        trace.append({"tool": name, "args": args or {}, "result": result})
        return result

    # -- LLM path --------------------------------------------------------
    def _gemini(self, question: str, trace: list[dict], allowed: list[str], role: str):
        """Returns (answer_text or None, signal or None)."""
        # Don't rely on another module having loaded the root .env first.
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL")
        if not api_key or not model_name:
            return None, None
        import google.generativeai as genai  # deprecated SDK, but it is the one installed

        restricted = [t.topic for n, t in self.tools.items() if n not in allowed and t.topic]
        restricted_rule = ""
        if restricted:
            restricted_rule = ("- These topics are reserved for administrators; if asked about any of them, "
                               "call report_restricted: " + "; ".join(restricted + [ACTION_TOPIC]) + ".\n")
        prompt = SYSTEM_PROMPT_TEMPLATE.format(role_label=ROLE_LABELS.get(role, role),
                                               restricted_rule=restricted_rule)
        declarations = [{"name": n, "description": self.tools[n].description,
                         "parameters": self.tools[n].parameters} for n in allowed]
        declarations += [{"name": n, **spec} for n, spec in SIGNAL_TOOLS.items()
                         if n != "report_restricted" or restricted]

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name, tools=[{"function_declarations": declarations}],
                                      system_instruction=prompt)
        chat = model.start_chat()
        response = chat.send_message(question, request_options={"timeout": LLM_TIMEOUT_SECONDS})
        for _ in range(MAX_TOOL_ROUNDS):
            parts = response.candidates[0].content.parts
            calls = [p.function_call for p in parts if p.function_call and p.function_call.name]
            if not calls:
                return "".join(p.text for p in parts if getattr(p, "text", "")).strip() or None, None
            replies = []
            for call in calls:
                args = json.loads(json.dumps(dict(call.args), default=str))
                if call.name in SIGNAL_TOOLS:
                    return None, {"kind": call.name, **args}
                result = self._execute(call.name, args, trace, allowed)
                replies.append(genai.protos.Part(function_response=genai.protos.FunctionResponse(
                    name=call.name, response={"result": json.loads(json.dumps(result, default=str))})))
            response = chat.send_message(replies, request_options={"timeout": LLM_TIMEOUT_SECONDS})
        return None, None

    # -- rule path -------------------------------------------------------
    def _rule_based(self, question: str, trace: list[dict], allowed: list[str],
                    permissions: set[str]) -> Optional[dict]:
        """Keyword routing when the LLM is unavailable. Returns a signal or None."""
        q = question.lower()
        if any(w in q for w in ACTION_WORDS):
            if "m2.officers.view" not in permissions:
                return {"kind": "report_restricted", "topic": q}
            return {"kind": "report_insufficient",
                    "reason": "I can only look things up; I can't make changes such as managing officers, "
                              "roles or passwords, retraining the model or approving incidents"}
        calls = route_question(question, self.known_routes())
        if not any(name == "predict_delay" for name, _ in calls) and \
                any(w in q for w in ("predict", "prediction", "forecast")):
            return {"kind": "report_insufficient", "reason": "a delay prediction needs a train and a route",
                    "missing": "the train (for example PM-4082) and the route or destination (for example Kandy)"}
        blocked = [name for name, _ in calls if name not in allowed]
        for name, args in calls:
            if name in allowed:
                self._execute(name, args, trace, allowed)
        if blocked and not trace:
            return {"kind": "report_restricted", "topic": self.tools[blocked[0]].topic}
        if not calls:
            return {"kind": "report_out_of_scope"}
        return None

    # -- template path ---------------------------------------------------
    def _template_answer(self, trace: list[dict]) -> str:
        parts = []
        for call in trace:
            tool = self.tools.get(call["tool"])
            result = call["result"]
            if "error" in result:
                parts.append("I can't reach live data for that right now, so I won't guess.")
            elif tool and "forbidden" not in result:
                parts.append(tool.template(result, call["args"]))
        return "\n\n".join(dict.fromkeys(parts))

    # -- public ----------------------------------------------------------
    def ask(self, question: str, permissions: Optional[set[str]] = None, role: str = "admin") -> dict[str, Any]:
        if permissions is None:  # full access (admin)
            permissions = {t.permission for t in self.tools.values()} | {"m2.officers.view"}
        allowed = self.allowed_tools(permissions)
        trace: list[dict] = []
        method = "llm_tool_calling"
        answer: Optional[str] = None
        signal: Optional[dict] = None
        try:
            answer, signal = self._gemini(question, trace, allowed, role)
        except Exception as exc:
            logger.warning("Gemini unavailable for ops agent: %s", exc)
            answer, signal = None, None

        if answer and not trace:
            # Free text without any lookup is never shown: it is either an
            # unsupported claim or an improvised refusal. Re-route instead.
            answer = None
        if answer:
            ok, unsupported = numbers_grounded(answer, [c["result"] for c in trace], question)
            if not ok:
                logger.warning("ops agent answer rejected, ungrounded numbers: %s", unsupported)
                method = "template_after_guard"
                answer = None

        if answer is None and signal is None:
            if method == "llm_tool_calling":
                method = "rule_based_fallback"
            if not trace:
                signal = self._rule_based(question, trace, allowed, permissions)
            if signal is None:
                answer = self._template_answer(trace)

        results = [c["result"] for c in trace if "forbidden" not in c["result"]]
        if signal is not None:
            answer_type = {"report_restricted": "restricted", "report_insufficient": "insufficient_data",
                           "report_out_of_scope": "out_of_scope"}[signal["kind"]]
            answer = self._message(answer_type, allowed, role,
                                   topic=self._canonical_topic(_clean_phrase(signal.get("topic"), 90)),
                                   reason=_clean_phrase(signal.get("reason")),
                                   missing=_clean_phrase(signal.get("missing")))
            reason = _clean_phrase(signal.get("reason")).lower()
            if answer_type == "insufficient_data" and self.coverage and any(w in reason for w in DATE_WORDS):
                span = self.coverage()
                answer = self._message(answer_type, allowed, role, reason=(
                    f"the operations data covers {span.get('from')} to {span.get('to')} as a whole and "
                    "can't be broken down by a specific date or month"))
            known = next((r["known_routes"] for r in results if r.get("known_routes")), None)
            if answer_type == "insufficient_data" and known:
                answer += "\n\nKnown routes: " + ", ".join(known) + "."
        elif results and all("error" in r for r in results):
            answer_type = "unavailable"
            answer = self._message(answer_type, allowed, role)
        elif any("not_found" in r for r in results):
            answer_type = "insufficient_data"
            answer = "I don't have enough information to answer that. " + (answer or "")
        else:
            answer_type = "answer"

        sources, highlights = [], []
        for call in trace:
            tool = self.tools.get(call["tool"])
            result = call["result"]
            if tool is None or "forbidden" in result:
                continue
            if "error" in result:
                sources.append({"tool": call["tool"], "label": f"{call['tool']}: live data unavailable"})
                continue
            sources.append({"tool": call["tool"], "label": tool.source_label(result, call["args"])})
            highlights.extend(tool.highlights(result))

        return {
            "answer": answer,
            "answer_type": answer_type,
            "sources": sources,
            "highlights": highlights[:4],
            "tool_calls_made": [{"tool": c["tool"], "args": c["args"],
                                 "ok": not ({"error", "forbidden"} & set(c["result"]))} for c in trace],
            "answer_method": method,
        }


# ---------------------------------------------------------------- history

LOCAL_HISTORY_PATH = Path(__file__).parent / "data" / "ops_agent_queries.jsonl"


class QueryHistory:
    """ops_agent_queries: Supabase primary, local JSONL mirror."""

    def __init__(self, get_client: Callable[[], Any]):
        self.get_client = get_client

    def _local_rows(self) -> list[dict]:
        try:
            return [json.loads(line) for line in LOCAL_HISTORY_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError):
            return []

    def record(self, admin_user_id: str, question: str, response: dict) -> dict:
        row = {
            "id": str(uuid.uuid4()),
            "admin_user_id": admin_user_id,
            "question": question,
            "answer": response["answer"],
            "answer_type": response.get("answer_type", "answer"),
            "tool_calls_made": response["tool_calls_made"],
            "sources": response["sources"],
            "highlights": response["highlights"],
            "answer_method": response.get("answer_method"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        stored = "local"
        client = self.get_client()
        if client is not None:
            try:
                try:
                    client.table("ops_agent_queries").insert(row).execute()
                except Exception:
                    # answer_method column not migrated yet: keep history working without it
                    client.table("ops_agent_queries").insert(
                        {k: v for k, v in row.items() if k != "answer_method"}).execute()
                stored = "supabase"
            except Exception as exc:
                logger.info("ops_agent_queries not in Supabase yet, keeping local copy: %s", exc.__class__.__name__)
        try:
            LOCAL_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOCAL_HISTORY_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
        except OSError as exc:
            logger.warning("could not mirror ops agent query locally: %s", exc)
        return {"row": row, "stored": stored}

    def list(self, admin_user_id: str, limit: int = 50, offset: int = 0) -> dict:
        client = self.get_client()
        if client is not None:
            try:
                res = (client.table("ops_agent_queries").select("*")
                       .eq("admin_user_id", admin_user_id)
                       .order("created_at", desc=True)
                       .range(offset, offset + limit - 1).execute())
                return {"rows": res.data or [], "source": "supabase"}
            except Exception:
                pass
        rows = [r for r in self._local_rows() if r.get("admin_user_id") == admin_user_id]
        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return {"rows": rows[offset:offset + limit], "source": "local"}
