"""
cancellation/rules.py
---------------------
Deterministic financial and eligibility business rules for RailSense AI.

Features:
1. Strict Decimal arithmetic with exact two-place quantization.
2. Evaluates time remaining until scheduled departure against DEMO policy rules.
3. Incorporates categorical exceptions (duplicate_booking, service_issue, personal_emergency).
4. Returns:
   - eligibility: 'ELIGIBLE' | 'PARTIAL_REFUND' | 'FULL_REFUND' | 'INELIGIBLE'
   - suggested_refund: Decimal (quantized to 0.01)
   - refund_percentage: int
   - policy_rule_applied: citation string
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

TWO_PLACES = Decimal("0.01")


class CancellationCalculationResult:
    def __init__(
        self,
        eligibility: str,
        suggested_refund: Decimal,
        refund_percentage: int,
        deduction_amount: Decimal,
        policy_rule_applied: str,
        hours_to_departure: float,
    ):
        self.eligibility = eligibility
        self.suggested_refund = suggested_refund
        self.refund_percentage = refund_percentage
        self.deduction_amount = deduction_amount
        self.policy_rule_applied = policy_rule_applied
        self.hours_to_departure = hours_to_departure

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligibility": self.eligibility,
            "suggested_refund": str(self.suggested_refund),
            "refund_percentage": self.refund_percentage,
            "deduction_amount": str(self.deduction_amount),
            "policy_rule_applied": self.policy_rule_applied,
            "hours_to_departure": round(self.hours_to_departure, 1),
        }


def calculate_cancellation_refund(
    fare: Decimal,
    travel_date: date,
    departure_time: time | None = None,
    reason_category: str = "other",
    current_time: datetime | None = None,
) -> CancellationCalculationResult:
    """
    Deterministically calculate suggested refund and eligibility.
    No LLM is ever used to calculate financial figures.
    """
    if not isinstance(fare, Decimal):
        fare = Decimal(str(fare))

    if current_time is None:
        current_time = datetime.now(timezone.utc)
    elif current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    # Compute scheduled departure timestamp (assume Asia/Colombo UTC+5:30 or generic UTC)
    dep_time = departure_time or time(7, 0)
    scheduled_departure = datetime.combine(travel_date, dep_time).replace(tzinfo=timezone.utc)

    time_delta = scheduled_departure - current_time
    hours_to_departure = time_delta.total_seconds() / 3600.0

    # 1. Special Case: Railway Service Disruption / Issue (100% full refund)
    if reason_category == "service_issue":
        refund = fare.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        return CancellationCalculationResult(
            eligibility="FULL_REFUND",
            suggested_refund=refund,
            refund_percentage=100,
            deduction_amount=Decimal("0.00"),
            policy_rule_applied="POL-REF-003 §2.2: 100% full refund for Railway Service Disruption",
            hours_to_departure=hours_to_departure,
        )

    # 2. Special Case: Duplicate Booking (100% full refund)
    if reason_category == "duplicate_booking":
        refund = fare.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        return CancellationCalculationResult(
            eligibility="ELIGIBLE",
            suggested_refund=refund,
            refund_percentage=100,
            deduction_amount=Decimal("0.00"),
            policy_rule_applied="POL-REF-003 §2.1: 100% full refund for verified duplicate booking",
            hours_to_departure=hours_to_departure,
        )

    # 3. Special Case: Personal Medical Emergency (80% compassionate refund)
    if reason_category == "personal_emergency":
        refund = (fare * Decimal("0.80")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        deduction = (fare - refund).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        return CancellationCalculationResult(
            eligibility="ELIGIBLE",
            suggested_refund=refund,
            refund_percentage=80,
            deduction_amount=deduction,
            policy_rule_applied="POL-REF-003 §2.3: 80% compassionate refund for certified personal emergency",
            hours_to_departure=hours_to_departure,
        )

    # 4. Standard Schedule-Based Tier Calculations
    if hours_to_departure >= 48.0:
        # Tier 1 (>48 Hours): 75% refund, 25% administrative fee
        refund = (fare * Decimal("0.75")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        deduction = (fare - refund).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        return CancellationCalculationResult(
            eligibility="ELIGIBLE",
            suggested_refund=refund,
            refund_percentage=75,
            deduction_amount=deduction,
            policy_rule_applied="POL-REF-003 §1.1: 75% refund for advance voluntary cancellation (>48h notice)",
            hours_to_departure=hours_to_departure,
        )
    elif hours_to_departure >= 24.0:
        # Tier 2 (24 to 48 Hours): 50% refund, 50% deduction
        refund = (fare * Decimal("0.50")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        deduction = (fare - refund).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        return CancellationCalculationResult(
            eligibility="PARTIAL_REFUND",
            suggested_refund=refund,
            refund_percentage=50,
            deduction_amount=deduction,
            policy_rule_applied="POL-REF-003 §1.2: 50% partial refund for standard voluntary cancellation (24-48h notice)",
            hours_to_departure=hours_to_departure,
        )
    else:
        # Tier 3 (<24 Hours): 0% non-refundable
        return CancellationCalculationResult(
            eligibility="INELIGIBLE",
            suggested_refund=Decimal("0.00"),
            refund_percentage=0,
            deduction_amount=fare.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
            policy_rule_applied="POL-REF-003 §1.3: Non-refundable for late cancellation (<24h notice)",
            hours_to_departure=hours_to_departure,
        )
