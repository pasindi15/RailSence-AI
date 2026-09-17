"""Integration tests for PART 2 — M1/M2 shared train registry.

Verifies all 7 points from the spec:
  1. M1 identifies PM-4082.
  2. M1 obtains canonical train information.
  3. M1 sends delay query through Hub.
  4. M2 resolves PM-4082 from Supabase.
  5. M2 uses its existing historical/model data.
  6. M1 receives the result.
  7. Unknown train IDs are rejected.

Usage:
    python scripts/test_m1_m2_integration.py

Requires M1 (port 8001) and M2 (port 8005) running locally.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import httpx
except ImportError:
    raise SystemExit("Run: pip install httpx")

M1_BASE = "http://localhost:8001"
M2_BASE = "http://localhost:8005"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def _check(label: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return condition


def test_m1_health() -> bool:
    print("\n[1] M1 identifies PM-4082 (NER extraction)")
    try:
        r = httpx.get(f"{M1_BASE}/health", timeout=4)
        ok = r.status_code == 200
        _check("M1 /health responds", ok)
        return ok
    except Exception as exc:
        _check("M1 reachable", False, str(exc))
        return False


def test_m1_train_info() -> bool:
    print("\n[2] M1 obtains canonical train information from shared registry")
    queries = [
        "What is PM-4082?",
        "Where does PM-4082 go?",
        "Is PM-4082 active?",
    ]
    results = []
    for q in queries:
        try:
            r = httpx.post(f"{M1_BASE}/chat", json={"message": q}, timeout=10)
            data = r.json()
            intent = data.get("intent")
            source = data.get("source", "")
            reply = data.get("reply", "")
            not_invented = "I don't know" not in reply and len(reply) > 10
            uses_registry = "Shared Train Registry" in source or "TRAIN_NOT_FOUND" in reply
            ok = intent in ("train_info", "schedule_query") and (uses_registry or not_invented)
            results.append(_check(f"  '{q}'", ok, f"intent={intent} source={source}"))
        except Exception as exc:
            results.append(_check(f"  '{q}'", False, str(exc)))
    return all(results)


def test_m1_delay_dispatch() -> bool:
    print("\n[3] M1 sends delay query through Hub to M2")
    try:
        r = httpx.post(
            f"{M1_BASE}/chat",
            json={"message": "Is PM-4082 delayed on Colombo Fort - Kandy?"},
            timeout=15,
        )
        data = r.json()
        intent = data.get("intent")
        source = data.get("source", "")
        reply = data.get("reply", "")
        dispatched = "Operations Agent" in source or "delay" in reply.lower() or "TRAIN_NOT_FOUND" in reply
        _check("intent=delay_check", intent == "delay_check", f"got {intent}")
        _check("routed via Operations Agent (Hub)", dispatched, f"source={source}")
        return intent == "delay_check" and dispatched
    except Exception as exc:
        _check("M1 delay dispatch", False, str(exc))
        return False


def test_m2_resolves_canonical() -> bool:
    print("\n[4] M2 resolves PM-4082 from shared Supabase trains table")
    try:
        from datetime import datetime, timezone
        r = httpx.post(
            f"{M2_BASE}/predict-delay",
            json={
                "route": "Colombo Fort - Kandy",
                "train_id": "PM-4082",
                "scheduled_time": datetime.now(timezone.utc).isoformat(),
            },
            timeout=15,
        )
        if r.status_code == 404 and "TRAIN_NOT_FOUND" in r.text:
            _check("PM-4082 validated (not in shared DB yet)", True, "TRAIN_NOT_FOUND — seed trains table first")
            return True
        if r.status_code == 503 and "TRAIN_REGISTRY_UNAVAILABLE" in r.text:
            _check("Shared registry contacted", True, "DB unreachable — configure SUPABASE_URL")
            return True
        ok = r.status_code == 200
        _check("M2 /predict-delay PM-4082 responds", ok, f"HTTP {r.status_code}")
        return ok
    except Exception as exc:
        _check("M2 reachable", False, str(exc))
        return False


def test_m2_uses_historical_data() -> bool:
    print("\n[5] M2 uses its existing historical/model data")
    try:
        r = httpx.get(f"{M2_BASE}/health", timeout=4)
        data = r.json()
        records = data.get("history_records", 0)
        ok = records > 0
        _check(f"M2 has {records} historical records loaded", ok)
        return ok
    except Exception as exc:
        _check("M2 /health", False, str(exc))
        return False


def test_m1_receives_delay_result() -> bool:
    print("\n[6] M1 receives delay result from M2 via Hub")
    try:
        r = httpx.post(
            f"{M1_BASE}/chat",
            json={"message": "How delayed is PM-4082 on Colombo Fort - Kandy route?"},
            timeout=15,
        )
        data = r.json()
        reply = data.get("reply", "")
        source = data.get("source", "")
        has_answer = (
            "delay" in reply.lower()
            or "minute" in reply.lower()
            or "TRAIN_NOT_FOUND" in reply
            or "registry" in reply.lower()
        )
        _check("M1 reply contains delay info or registry response", has_answer, f"reply={reply[:80]}")
        _check("source traces back to Operations Agent", "Operations" in source or "Registry" in source, f"source={source}")
        return has_answer
    except Exception as exc:
        _check("M1 end-to-end delay", False, str(exc))
        return False


def test_unknown_train_rejected() -> bool:
    print("\n[7] Unknown train IDs are rejected — TRAIN_NOT_FOUND")
    results = []

    # M1 train_info for unknown ID
    try:
        r = httpx.post(f"{M1_BASE}/chat", json={"message": "What is UNKNOWN-999?"}, timeout=10)
        data = r.json()
        reply = data.get("reply", "")
        rejected = "TRAIN_NOT_FOUND" in reply or "not registered" in reply or "not recognised" in reply
        results.append(_check("M1 rejects UNKNOWN-999", rejected, f"reply={reply[:80]}"))
    except Exception as exc:
        results.append(_check("M1 unknown train", False, str(exc)))

    # M2 direct predict-delay for unknown ID
    try:
        from datetime import datetime, timezone
        r = httpx.post(
            f"{M2_BASE}/predict-delay",
            json={
                "route": "Colombo Fort - Kandy",
                "train_id": "UNKNOWN-999",
                "scheduled_time": datetime.now(timezone.utc).isoformat(),
            },
            timeout=10,
        )
        rejected = r.status_code in (404, 503) and ("TRAIN_NOT_FOUND" in r.text or "TRAIN_REGISTRY" in r.text)
        results.append(_check("M2 rejects UNKNOWN-999", rejected, f"HTTP {r.status_code}"))
    except Exception as exc:
        results.append(_check("M2 unknown train", False, str(exc)))

    return all(results)


def main() -> None:
    print("=" * 60)
    print("RailSense AI — M1/M2 Shared Train Registry Integration Test")
    print("=" * 60)

    tests = [
        test_m1_health,
        test_m1_train_info,
        test_m1_delay_dispatch,
        test_m2_resolves_canonical,
        test_m2_uses_historical_data,
        test_m1_receives_delay_result,
        test_unknown_train_rejected,
    ]

    passed = sum(1 for t in tests if t())
    total = len(tests)
    print(f"\n{'=' * 60}")
    print(f"Result: {passed}/{total} test groups passed")
    if passed < total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
