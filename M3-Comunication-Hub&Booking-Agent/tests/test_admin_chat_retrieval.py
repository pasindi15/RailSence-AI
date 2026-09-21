"""
tests/test_admin_chat_retrieval.py
----------------------------------
Test suite for structured database retrieval layer in the Admin Booking Intelligence Assistant:
- Live seat availability calculation (capacity - confirmed - holds)
- Cancellation queue filtering & case retrieval
- Fraud review queue filtering & risk score retrieval
- Passenger manifest retrieval with masked NICs
- Single booking timeline lookup
- Daily booking summary aggregation
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_M3_ROOT = _TESTS_DIR.parent
_BOOKING_AGENT_DIR = _M3_ROOT / "booking-agent"

for p in (str(_M3_ROOT), str(_BOOKING_AGENT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from database.database import SessionLocal, init_db
from database.models import (
    Booking,
    BookingStatus,
    CancellationRequest,
    CancellationStatus,
    FraudReview,
    FraudReviewStatus,
    Passenger,
    BookingPassenger,
    Train,
    TrainSchedule,
)
from admin_chat.retrieval import (
    retrieve_booking_lookup,
    retrieve_booking_summary,
    retrieve_cancellations,
    retrieve_fraud_reviews,
    retrieve_manifest,
    retrieve_seat_availability,
)
from shared.nic import hash_nic, mask_nic


@pytest.fixture(scope="module", autouse=True)
def setup_test_data():
    init_db(seed=True)
    with SessionLocal() as db:
        # Create a test train and schedule if missing
        train = db.query(Train).filter(Train.train_id == "1005").first()
        if not train:
            train = Train(train_id="1005", train_name="Udarata Menike", route="Colombo - Badulla", active=True)
            db.add(train)
            db.flush()

        tom = date.today() + timedelta(days=1)
        sched = db.query(TrainSchedule).filter(
            TrainSchedule.train_id == train.id,
            TrainSchedule.travel_date == tom,
        ).first()
        if not sched:
            sched = TrainSchedule(
                train_id=train.id,
                from_station="Colombo",
                to_station="Badulla",
                travel_date=tom,
                departure_time=datetime.strptime("05:55", "%H:%M").time(),
                arrival_time=datetime.strptime("15:30", "%H:%M").time(),
                first_class_capacity=44,
                second_class_capacity=100,
                service_status="SCHEDULED",
            )
            db.add(sched)
            db.flush()

        # Add a test booking
        bkg = db.query(Booking).filter(Booking.booking_reference == "RS-RET-01").first()
        if not bkg:
            bkg = Booking(
                booking_reference="RS-RET-01",
                user_id="admin_test_user",
                train_id=train.id,
                schedule_id=sched.id,
                from_station="Colombo",
                to_station="Badulla",
                travel_date=tom,
                seat_class="First Class",
                passenger_count=2,
                fare=3600.00,
                status=BookingStatus.CONFIRMED,
            )
            db.add(bkg)
            db.flush()

            # Add passenger
            p_nic = "199412345678"
            p = db.query(Passenger).filter(Passenger.nic_hash == hash_nic(p_nic)).first()
            if not p:
                p = Passenger(nic_hash=hash_nic(p_nic), nic_masked=mask_nic(p_nic), full_name="Saman Perera")
                db.add(p)
                db.flush()
            db.add(BookingPassenger(booking_id=bkg.id, passenger_id=p.id))

        # Add a test fraud review
        fr = db.query(FraudReview).filter(FraudReview.case_reference == "FR-9901").first()
        if not fr:
            fr = FraudReview(
                case_reference="FR-9901",
                booking_payload='{"train_id": "1005", "travel_date": "2026-09-25"}',
                primary_nic_hash=hash_nic("200012345678"),
                risk_score=0.85,
                risk_level="HIGH",
                recommended_action="HOLD",
                reasons='["high velocity", "multiple attempts"]',
                status=FraudReviewStatus.PENDING_REVIEW,
            )
            db.add(fr)

        # Add a test cancellation
        cr = db.query(CancellationRequest).filter(CancellationRequest.case_reference == "CAN-9901").first()
        if not cr:
            cr = CancellationRequest(
                case_reference="CAN-9901",
                booking_id=bkg.id,
                reason="Work schedule changed",
                reason_category="schedule_change",
                suggested_refund=2700.00,
                status=CancellationStatus.PENDING_ADMIN_REVIEW,
            )
            db.add(cr)

        db.commit()


class TestAdminChatRetrieval:

    def test_seat_availability_calculation(self):
        """1. Available seats = capacity - confirmed - holds."""
        with SessionLocal() as db:
            tom = (date.today() + timedelta(days=1)).isoformat()
            res = retrieve_seat_availability(db, {
                "train_id": "1005",
                "travel_date": tom,
                "seat_class": "First Class",
            })
            assert res["found"] is True
            assert len(res["records"]) > 0
            rec = res["records"][0]
            assert rec["seat_class"] == "First Class"
            assert rec["capacity"] > 0
            assert rec["confirmed"] >= 0
            assert rec["available"] == rec["capacity"] - rec["confirmed"] - rec["held"]

    def test_fraud_review_case_and_count_retrieval(self):
        """2. Fraud review queue queries."""
        with SessionLocal() as db:
            # Case lookup
            res_case = retrieve_fraud_reviews(db, {"case_reference": "FR-9901"})
            assert res_case["type"] == "single_case"
            assert res_case["risk_level"] == "HIGH"
            assert res_case["risk_score"] == 0.85

            # Count lookup
            res_cnt = retrieve_fraud_reviews(db, {"is_count_request": True, "review_status": "PENDING"})
            assert res_cnt["type"] == "count"
            assert res_cnt["count"] >= 1

    def test_cancellation_queue_and_case_retrieval(self):
        """3. Cancellation queue queries."""
        with SessionLocal() as db:
            # Case lookup
            res_case = retrieve_cancellations(db, {"case_reference": "CAN-9901"})
            assert res_case["type"] == "single_case"
            assert res_case["booking_reference"] == "RS-RET-01"
            assert float(res_case["suggested_refund"]) == 2700.00

            # Count lookup
            res_cnt = retrieve_cancellations(db, {"is_count_request": True, "review_status": "PENDING"})
            assert res_cnt["type"] == "count"
            assert res_cnt["count"] >= 1

    def test_manifest_retrieval_masks_nic(self):
        """4. Manifest returns masked NICs and accurate passenger count."""
        with SessionLocal() as db:
            tom = (date.today() + timedelta(days=1)).isoformat()
            res = retrieve_manifest(db, {
                "train_id": "1005",
                "travel_date": tom,
            })
            assert res["type"] == "manifest"
            assert res["total_bookings"] >= 1
            for bkg in res["bookings"]:
                for p in bkg["passengers"]:
                    assert p["nic_masked"].startswith("****") or p["nic_masked"].startswith("******")
                    assert not (len(p["nic_masked"]) in (10, 12) and p["nic_masked"].isdigit())

    def test_booking_lookup_timeline(self):
        """5. Single booking lookup returns linked cancellation and status."""
        with SessionLocal() as db:
            res = retrieve_booking_lookup(db, "RS-RET-01")
            assert res["found"] is True
            assert res["booking_reference"] == "RS-RET-01"
            assert "Menike" in res["train_name"]
            assert res["cancellation"] is not None
            assert res["cancellation"]["case_reference"] == "CAN-9901"

    def test_booking_summary_daily_counts(self):
        """6. Daily booking summary aggregation."""
        with SessionLocal() as db:
            res = retrieve_booking_summary(db, {})
            assert "confirmed_bookings" in res
            assert "pending_cancellations" in res
            assert "pending_fraud_reviews" in res
            assert res["pending_fraud_reviews"] >= 1
            assert res["pending_cancellations"] >= 1
