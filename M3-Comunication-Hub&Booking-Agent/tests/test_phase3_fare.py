"""
tests/test_phase3_fare.py
-------------------------
RailSense AI — Member C Phase 3 Deterministic Fare Calculation Tests.

Verifies:
  1. Known route and class fare lookup (Colombo -> Kandy, First Class & Second Class)
  2. Multi-passenger calculation (total_fare = fare_per_passenger * passenger_count)
  3. Unknown fare rule raises FareNotFoundError (does not invent or hallucinate fares)
  4. Different classes on the same route yield distinct fares
  5. Exact Decimal accuracy (no binary floating point representation or rounding errors)
  6. Case-insensitive and whitespace-tolerant station and seat class lookup
  7. Bi-directional route support (Colombo <-> Kandy)
  8. Integration with BookingService orchestrator
  9. Invalid passenger counts reject with InvalidBookingError
  10. Purely deterministic and offline execution without external API or LLM calls
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
MEMBER_C = os.path.dirname(os.path.dirname(__file__))
BOOKING_AGENT = os.path.join(MEMBER_C, "booking-agent")

for p in (MEMBER_C, BOOKING_AGENT):
    if p not in sys.path:
        sys.path.insert(0, p)

from booking import (
    BookingService,
    FareBreakdown,
    FareNotFoundError,
    InvalidBookingError,
    calculate_fare,
    get_fare_per_passenger,
)
from booking.fare import DEMO_FARE_RULES


class TestDeterministicFareCalculation:

    def test_known_route_first_class_fare(self):
        """Known route Colombo -> Kandy First Class must return configured base fare."""
        fare_unit = get_fare_per_passenger("Colombo", "Kandy", "First Class")
        assert fare_unit == Decimal("2500.00")
        assert isinstance(fare_unit, Decimal)

        breakdown = calculate_fare(
            from_station="Colombo",
            to_station="Kandy",
            seat_class="First Class",
            passenger_count=1,
        )
        assert breakdown.from_station == "Colombo"
        assert breakdown.to_station == "Kandy"
        assert breakdown.seat_class == "First Class"
        assert breakdown.passenger_count == 1
        assert breakdown.fare_per_passenger == Decimal("2500.00")
        assert breakdown.total_fare == Decimal("2500.00")

    def test_known_route_second_class_fare(self):
        """Known route Colombo -> Kandy Second Class must return configured base fare."""
        breakdown = calculate_fare(
            from_station="Colombo",
            to_station="Kandy",
            seat_class="Second Class",
            passenger_count=1,
        )
        assert breakdown.fare_per_passenger == Decimal("1200.00")
        assert breakdown.total_fare == Decimal("1200.00")

    def test_multiple_passengers_multiplication(self):
        """Total fare must strictly equal fare_per_passenger * passenger_count."""
        # Colombo -> Kandy Second Class = 1200.00 * 4 passengers = 4800.00
        breakdown = calculate_fare(
            from_station="Colombo",
            to_station="Kandy",
            seat_class="Second Class",
            passenger_count=4,
        )
        assert breakdown.passenger_count == 4
        assert breakdown.fare_per_passenger == Decimal("1200.00")
        assert breakdown.total_fare == Decimal("4800.00")

    def test_different_classes_different_fares(self):
        """First Class and Second Class must have distinct prices for the same route."""
        fc = calculate_fare(
            from_station="Colombo",
            to_station="Galle",
            seat_class="First Class",
            passenger_count=1,
        )
        sc = calculate_fare(
            from_station="Colombo",
            to_station="Galle",
            seat_class="Second Class",
            passenger_count=1,
        )
        assert fc.total_fare == Decimal("1800.00")
        assert sc.total_fare == Decimal("800.00")
        assert fc.total_fare > sc.total_fare

    def test_unknown_route_raises_fare_not_found(self):
        """Routes without a deterministic rule must raise FareNotFoundError without inventing a price."""
        with pytest.raises(FareNotFoundError) as exc_info:
            calculate_fare(
                from_station="Colombo",
                to_station="Jaffna",
                seat_class="First Class",
                passenger_count=1,
            )
        err = exc_info.value
        assert "Colombo -> Jaffna" in str(err)
        assert err.seat_class == "First Class"

    def test_unknown_class_raises_fare_not_found_with_custom_rules(self):
        """Missing class in custom rule table must raise FareNotFoundError."""
        custom_rules = {
            ("colombo", "kandy"): {
                "Second Class": Decimal("1000.00")
                # Missing First Class
            }
        }
        with pytest.raises(FareNotFoundError) as exc_info:
            calculate_fare(
                from_station="Colombo",
                to_station="Kandy",
                seat_class="First Class",
                passenger_count=1,
                fare_rules=custom_rules,
            )
        assert "First Class" in str(exc_info.value)

    def test_decimal_precision_and_no_floating_point(self):
        """Monetary calculations must use Decimal and avoid binary floating point anomalies."""
        custom_rules = {
            ("station_a", "station_b"): {
                "First Class": Decimal("1234.56"),
            }
        }
        breakdown = calculate_fare(
            from_station="station_a",
            to_station="station_b",
            seat_class="First Class",
            passenger_count=3,
            fare_rules=custom_rules,
        )
        assert breakdown.total_fare == Decimal("3703.68")
        assert isinstance(breakdown.fare_per_passenger, Decimal)
        assert isinstance(breakdown.total_fare, Decimal)
        # Ensure not float
        assert not isinstance(breakdown.total_fare, float)

    def test_case_and_whitespace_insensitivity(self):
        """Station names and class inputs with varying case/whitespace must resolve properly."""
        breakdown = calculate_fare(
            from_station="  colombo  ",
            to_station="KANDY ",
            seat_class="2nd class",
            passenger_count=2,
        )
        assert breakdown.fare_per_passenger == Decimal("1200.00")
        assert breakdown.total_fare == Decimal("2400.00")
        assert breakdown.seat_class == "Second Class"

    def test_bidirectional_route(self):
        """Route from Kandy -> Colombo must cost the same as Colombo -> Kandy."""
        outbound = calculate_fare("Colombo", "Kandy", "First Class", 1)
        inbound = calculate_fare("Kandy", "Colombo", "First Class", 1)
        assert outbound.total_fare == inbound.total_fare == Decimal("2500.00")

    def test_invalid_passenger_count_rejected(self):
        """passenger_count < 1 must be rejected with InvalidBookingError."""
        with pytest.raises(InvalidBookingError):
            calculate_fare("Colombo", "Kandy", "First Class", 0)
        with pytest.raises(InvalidBookingError):
            calculate_fare("Colombo", "Kandy", "First Class", -2)

    def test_missing_stations_rejected(self):
        """Empty station strings must raise InvalidBookingError."""
        with pytest.raises(InvalidBookingError):
            calculate_fare("", "Kandy", "First Class", 1)
        with pytest.raises(InvalidBookingError):
            calculate_fare("Colombo", "", "First Class", 1)

    def test_service_orchestrator_integration(self):
        """BookingService.compute_fare must integrate cleanly with the fare engine."""
        service = BookingService(db=None)
        breakdown = service.compute_fare(
            from_station="Colombo",
            to_station="Kandy",
            seat_class="Second Class",
            passenger_count=3,
        )
        assert isinstance(breakdown, FareBreakdown)
        assert breakdown.total_fare == Decimal("3600.00")
