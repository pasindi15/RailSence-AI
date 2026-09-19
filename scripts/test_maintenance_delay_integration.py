"""Integration test — Maintenance-enriched delay response.

Flow under test:
  1. Engineer flags PM-4082 for maintenance via M4.
  2. Passenger asks M1 about a delay on PM-4082.
  3. M1 sends delay_check to M2; M2 returns a maintenance-related reason.
  4. M1 detects the keyword, queries M4 train_status_query via Hub.
  5. M4 confirms the train is under maintenance with reason + ETA.
  6. M1 returns ONE combined reply: delay + maintenance context.
  7. Engineer clears the flag — next M1 reply no longer includes M4 context.

Usage:
    python scripts/test_maintenance_delay_integration.py

Requires M1 (8001), Hub/M3 (8002), M2 Operations (8005), M4 (8006) running.
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
M4_BASE = "http://localhost:8006"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

TEST_TRAIN_ID = "PM-4082"


def _check(label: str, condition: bool, detail: str = "") -> bool:
    tag = PASS if condition else FAIL
    print(f"  [{tag}] {label}" + (f" — {detail}" if detail else ""))
    return condition


def _m4_flag(train_id: str, reason: str, severity: str = "AMBER") -> bool:
    try:
        r = httpx.post(
            f"{M4_BASE}/api/flag-train",
            json={"train_id": train_id, "reason": reason, "severity": severity, "flagged_by": "test-engineer"},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def _m4_clear(train_id: str) -> bool:
    try:
        r = httpx.delete(f"{M4_BASE}/api/flag-train/{train_id}", timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def _m1_chat(message: str) -> dict:
    r = httpx.post(f"{M1_BASE}/chat", json={"message": message}, timeout=20)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------

def test_m1_reachable() -> bool:
    print("\n[1] M1 Passenger Agent reachable")
    try:
        r = httpx.get(f"{M1_BASE}/health", timeout=5)
        ok = r.status_code in (200, 404)
        _check("M1 responds", ok, f"HTTP {r.status_code}")
        return ok
    except Exception as exc:
        _check("M1 reachable", False, str(exc))
        return False


def test_m4_reachable() -> bool:
    print("\n[2] M4 Maintenance Agent reachable")
    try:
        r = httpx.get(f"{M4_BASE}/health", timeout=5)
        ok = r.status_code in (200, 404)
        _check("M4 responds", ok, f"HTTP {r.status_code}")
        return ok
    except Exception as exc:
        _check("M4 reachable", False, str(exc))
        return False


def test_delay_no_maintenance_flag() -> bool:
    print(f"\n[3] Delay query for {TEST_TRAIN_ID} — no maintenance flag active")
    _m4_clear(TEST_TRAIN_ID)
    try:
        data = _m1_chat(f"Is train {TEST_TRAIN_ID} delayed?")
        reply = data.get("reply", "")
        source = data.get("source", "")
        has_reply = len(reply) > 5
        no_maint_context = "maintenance update" not in reply.lower()
        _check("M1 returns a delay reply", has_reply, f"reply={reply[:120]}")
        _check("No maintenance context (flag not set)", no_maint_context, f"source={source}")
        return has_reply
    except Exception as exc:
        _check("M1 responded", False, str(exc))
        return False


def test_flag_train_for_maintenance() -> bool:
    print(f"\n[4] Engineer flags {TEST_TRAIN_ID} for maintenance via M4")
    ok = _m4_flag(TEST_TRAIN_ID, reason="Engine fault — under repair", severity="RED")
    _check(f"{TEST_TRAIN_ID} flagged via M4", ok, "POST /api/flag-train")
    return ok


def test_delay_with_maintenance_context() -> bool:
    print(f"\n[5] Delay query — M1 enriches reply with M4 maintenance context")
    try:
        data = _m1_chat(
            f"Is train {TEST_TRAIN_ID} delayed? I heard there was a maintenance issue."
        )
        reply = data.get("reply", "")
        source = data.get("source", "")
        print(f"     reply : {reply[:200]}")
        print(f"     source: {source}")

        has_delay_info = "delay" in reply.lower() or "minutes" in reply.lower()
        has_maint_context = "maintenance" in reply.lower()
        sources_both = "maintenance" in source.lower()

        _check("Reply contains delay information", has_delay_info, reply[:80])
        _check("Reply contains maintenance context from M4", has_maint_context, reply[:80])
        _check("Source attribute reflects both agents", sources_both, source)
        return has_delay_info and has_maint_context
    except Exception as exc:
        _check("M1 responded", False, str(exc))
        return False


def test_m4_hub_train_status_query() -> bool:
    print(f"\n[6] M4 train_status_query via Hub returns maintenance record")
    try:
        r = httpx.post(
            f"{M4_BASE}/hub/message",
            json={
                "message_id": "test-tsq-001",
                "sender_agent": "passenger-agent",
                "receiver_agent": "maintenance-agent",
                "intent": "train_status_query",
                "payload": {"train_id": TEST_TRAIN_ID},
                "timestamp": "2026-09-19T00:00:00Z",
            },
            timeout=10,
        )
        data = r.json()
        payload = data.get("payload", {})
        under_maint = payload.get("under_maintenance", False)
        reason_in_payload = bool(payload.get("reason"))
        _check("M4 responds to train_status_query", r.status_code == 200, f"HTTP {r.status_code}")
        _check("under_maintenance=True", under_maint, str(payload))
        _check("reason field present in payload", reason_in_payload, str(payload.get("reason", "")))
        return r.status_code == 200 and under_maint
    except Exception as exc:
        _check("M4 hub endpoint reachable", False, str(exc))
        return False


def test_clear_flag_and_recheck() -> bool:
    print(f"\n[7] Engineer clears flag — M1 delay reply no longer includes M4 maintenance context")
    cleared = _m4_clear(TEST_TRAIN_ID)
    _check(f"Flag cleared for {TEST_TRAIN_ID}", cleared, "DELETE /api/flag-train")
    if not cleared:
        return False
    try:
        data = _m1_chat(f"What is the delay status of train {TEST_TRAIN_ID}?")
        reply = data.get("reply", "")
        source = data.get("source", "")
        has_reply = len(reply) > 5
        no_maint_context = "maintenance update" not in reply.lower()
        _check("M1 returns a delay reply after flag cleared", has_reply, reply[:80])
        _check("No maintenance context in reply (flag cleared)", no_maint_context, f"source={source}")
        return has_reply and no_maint_context
    except Exception as exc:
        _check("M1 responded", False, str(exc))
        return False


# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 65)
    print("RailSense AI — Maintenance-Enriched Delay Response Integration Test")
    print("Tests M1 → M2 (delay) + M1 → M4 (maintenance context) via Hub")
    print("=" * 65)

    tests = [
        test_m1_reachable,
        test_m4_reachable,
        test_delay_no_maintenance_flag,
        test_flag_train_for_maintenance,
        test_delay_with_maintenance_context,
        test_m4_hub_train_status_query,
        test_clear_flag_and_recheck,
    ]

    passed = sum(1 for t in tests if t())
    total = len(tests)
    print(f"\n{'=' * 65}")
    print(f"Result: {passed}/{total} test groups passed")
    if passed < total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
