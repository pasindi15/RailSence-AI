"""
Source-consistency tests: the passenger FAQ (M1) must never contradict the
Booking Agent (M3), which owns fares, booking limits, cancellation and refund
rules. These read M3's executable code/policies directly, so if either side
changes without the other, a test fails instead of a passenger getting two
different answers.

M3 is read without importing its runtime (no database, no SQLAlchemy):
  - the fare table is parsed from booking/fare.py with `ast`
  - cancellation/rules.py is loaded by file path (it only uses the stdlib)
"""
import importlib.util
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from rag.embed_documents import chunk_markdown
from rag.sync_from_m3 import FARES_MD, load_m3_fare_rules, render_fares_md

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parents[1]
M3_BOOKING_AGENT = REPO_ROOT / "M3-Comunication-Hub&Booking-Agent" / "booking-agent"
M3_POLICIES = M3_BOOKING_AGENT / "cancellation" / "policies"
FAQ_DIR = BACKEND_DIR / "data" / "faq_docs"


def _section(doc: str, heading: str) -> str:
    chunks = {c["heading"]: c["text"] for c in chunk_markdown((FAQ_DIR / doc).read_text(encoding="utf-8"))}
    return chunks[heading]


def _line_pct(section: str, label: str) -> int:
    """First 'NN%' on the section line that contains `label`."""
    for line in section.splitlines():
        if label.lower() in line.lower():
            m = re.search(r"(\d+)%", line)
            assert m, f"no percentage on line for {label!r}: {line!r}"
            return int(m.group(1))
    raise AssertionError(f"no line containing {label!r}")


@pytest.fixture(scope="module")
def m3_refund_pct():
    spec = importlib.util.spec_from_file_location("m3_cancellation_rules", M3_BOOKING_AGENT / "cancellation" / "rules.py")
    rules = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rules)
    now = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)

    def pct(hours_before: float, reason: str = "other") -> int:
        departure = now + timedelta(hours=hours_before)
        return rules.calculate_cancellation_refund(
            fare=Decimal("1000.00"),
            travel_date=departure.date(),
            departure_time=departure.time(),
            reason_category=reason,
            current_time=now,
        ).refund_percentage

    return pct


# ----------------------------------------------------------------- fares ---

def test_fares_md_is_exactly_what_the_m3_fare_table_generates():
    assert FARES_MD.read_text(encoding="utf-8") == render_fares_md(load_m3_fare_rules()), (
        "fares.md is out of date with booking/fare.py - run `python -m rag.sync_from_m3` "
        "then `python -m rag.embed_documents`"
    )


def test_colombo_kandy_fare_matches_booking_system():
    rules = load_m3_fare_rules()
    assert rules[("colombo", "kandy")] == {"First Class": Decimal("2500.00"), "Second Class": Decimal("1200.00")}
    kandy = _section("fares.md", "Colombo Fort - Kandy")
    assert "First Class: LKR 2500 per seat" in kandy
    assert "Second Class: LKR 1200 per seat" in kandy


def test_every_fare_quoted_by_m1_exists_in_the_m3_table_and_no_extra_route_is_invented():
    rules = load_m3_fare_rules()
    m3_amounts_by_route = {
        frozenset(("Colombo Fort" if s == "colombo" else s.title() for s in route)): {int(a) for a in classes.values()}
        for route, classes in rules.items()
    }
    doc = FARES_MD.read_text(encoding="utf-8")
    seen_routes = set()
    for chunk in chunk_markdown(doc):
        m = re.fullmatch(r"(.+?) - (.+)", chunk["heading"])
        if not m:
            continue  # "How fares are calculated"
        route = frozenset(m.groups())
        seen_routes.add(route)
        assert route in m3_amounts_by_route, f"M1 lists a route the booking system cannot price: {chunk['heading']}"
        quoted = {int(x) for x in re.findall(r"LKR (\d+) per seat", chunk["text"])}
        assert quoted == m3_amounts_by_route[route], chunk["heading"]
    assert seen_routes == set(m3_amounts_by_route), "M1 is missing a route the booking system can price"


def test_no_unvalidated_fare_classes_or_discounts_are_quoted():
    text = FARES_MD.read_text(encoding="utf-8").lower()
    for stale in ("3rd class", "unreserved", "observation saloon", "1st class ac", "25% off", "50% off", "half fare"):
        assert stale not in text, f"unvalidated/legacy fare fact still present: {stale}"


# --------------------------------------------------------------- refunds ---

def test_refund_tiers_match_m3_refund_logic(m3_refund_pct):
    refunds = _section("policies.md", "Refunds")
    assert _line_pct(refunds, "More than 48 hours before departure") == m3_refund_pct(72) == 75
    assert _line_pct(refunds, "24 to 48 hours before departure") == m3_refund_pct(36) == 50
    assert _line_pct(refunds, "Less than 24 hours before departure") == m3_refund_pct(12) == 0


def test_refund_exceptions_match_m3_refund_logic(m3_refund_pct):
    refunds = _section("policies.md", "Refunds")
    assert _line_pct(refunds, "duplicate booking") == m3_refund_pct(72, "duplicate_booking") == 100
    assert _line_pct(refunds, "railway service disruption") == m3_refund_pct(12, "service_issue") == 100
    assert _line_pct(refunds, "certified personal emergency") == m3_refund_pct(12, "personal_emergency") == 80
    # schedule change with >48h notice is treated as a standard Tier 1 refund (POL-REF-003 2.4)
    assert _line_pct(refunds, "change of travel plans") == m3_refund_pct(72) == 75


def test_refund_figures_agree_with_the_approved_m3_refund_policy_text():
    policy = (M3_POLICIES / "refund_policy.md").read_text(encoding="utf-8")
    refunds = _section("policies.md", "Refunds")
    for pct in re.findall(r"(\d+)%", refunds):
        # every percentage M1 states (refund or deduction) appears in POL-REF-003
        assert f"{pct}%" in policy, f"M1 states {pct}% which POL-REF-003 does not contain"
    assert re.search(r"exceeding three \(3\) hours", policy)
    assert "more than 3 hours" in _section("policies.md", "Refunds")


def test_legacy_conflicting_refund_rules_are_gone():
    text = (FAQ_DIR / "policies.md").read_text(encoding="utf-8").lower()
    for stale in ("10% service charge", "2 hours before", "non-refundable once issued", "3rd class"):
        assert stale not in text, f"legacy rule contradicting M3 still present: {stale}"


# ---------------------------------------------------- booking / reservation ---

def test_booking_limits_match_m3_code_and_policy():
    booking_schema = (M3_BOOKING_AGENT / "schemas" / "booking.py").read_text(encoding="utf-8")
    limits = set(re.findall(r"passenger_count:\s*int\s*=\s*Field\(\.\.\.,\s*ge=1,\s*le=(\d+)", booking_schema))
    assert limits == {"10"}, f"M3 seat limit changed or is inconsistent: {limits}"
    rules = _section("policies.md", "Booking Rules")
    assert "at most 10 seats" in rules
    assert "30 days" in rules
    assert "thirty (30) days" in (M3_POLICIES / "booking_policy.md").read_text(encoding="utf-8")
    assert "RS-XXXXX" in rules and "RS-XXXXX" in (M3_POLICIES / "booking_policy.md").read_text(encoding="utf-8")


def test_reservation_rules_agree_with_m3():
    seating = _section("policies.md", "Reserved Seating")
    m3 = (M3_POLICIES / "reservation_rules.md").read_text(encoding="utf-8")
    assert "non-transferable" in m3 and "cannot be transferred" in seating
    assert "100% refund" in m3 and "100% refund" in seating
    # M3 has no 10-minute claim window or 1-hour booking cutoff; M1 must not claim one.
    text = (FAQ_DIR / "policies.md").read_text(encoding="utf-8").lower()
    assert "10 minutes" not in text and "1 hour before departure" not in text


# ------------------------------------------------------------ cancellation ---

def test_cancellation_faq_matches_human_review_requirement():
    cancelling = _section("policies.md", "Cancelling a Booking").lower()
    m3 = (M3_POLICIES / "cancellation_policy.md").read_text(encoding="utf-8")
    assert "No automated AI system" in m3 and "human administrator" in m3
    assert "administrator" in cancelling
    assert "stays confirmed until the administrator" in cancelling
    assert "cannot cancel a booking or pay a refund by itself" in cancelling
    for forbidden in ("instantly cancel", "automatically refund", "refunded immediately", "cancelled immediately"):
        assert forbidden not in cancelling


def test_cancellation_notice_tiers_match_m3_cancellation_policy():
    policy = (M3_POLICIES / "cancellation_policy.md").read_text(encoding="utf-8")
    assert "48 hours" in policy and "24 and 48 hours" in policy and "24 hours" in policy
    refunds = _section("policies.md", "Refunds")
    assert "More than 48 hours" in refunds and "24 to 48 hours" in refunds and "Less than 24 hours" in refunds


# ------------------------------------------- agent boundaries stay intact ---

def test_passenger_docs_do_not_expose_admin_security_or_engineering_content():
    combined = "\n".join(p.read_text(encoding="utf-8") for p in FAQ_DIR.glob("*.md"))
    for internal in (
        "PENDING_ADMIN_REVIEW", "PENDING_FRAUD_REVIEW", "POL-", "DEMO-SEC", "anomaly", "fraud",
        "60 second", "six (6)", "hoarding",          # security_review_policy.md thresholds
        "SLR-MM-", "pantograph", "bogie", "torque",   # M4 engineering manuals
    ):
        assert internal not in combined, f"internal/engineer-only content leaked into passenger FAQ: {internal}"
