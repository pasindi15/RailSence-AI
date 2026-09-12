"""
database/seed.py
----------------
Deterministic seed data for development and testing.

Controls:
- Not executed automatically on production startup.
- Designed for test fixtures and manual local development bootstrapping.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from .models import Train, TrainSchedule


def seed_test_train_data(db: Session) -> dict[str, Any]:
    """
    Seed standard development/test trains and schedules.

    Entities seeded:
    - Train 'PM-4082': Active (Intercity Express)
    - Train 'INACT-9999': Inactive (Decommissioned Railcar)
    - Schedule for PM-4082: Colombo -> Kandy on 2026-12-03
    - Schedule for PM-4082: Colombo -> Kandy on future date (today + 30 days)
    """
    # 1. Active Train
    train_pm4082 = db.query(Train).filter(Train.train_id == "PM-4082").first()
    if not train_pm4082:
        train_pm4082 = Train(
            train_id="PM-4082",
            train_name="Intercity Express",
            active=True,
        )
        db.add(train_pm4082)
        db.flush()

    # 2. Inactive Train
    train_inact = db.query(Train).filter(Train.train_id == "INACT-9999").first()
    if not train_inact:
        train_inact = Train(
            train_id="INACT-9999",
            train_name="Maintenance Railcar",
            active=False,
        )
        db.add(train_inact)
        db.flush()

    # 3. Schedule for PM-4082 (fixed target date 2026-12-03)
    target_date = date(2026, 12, 3)
    schedule_colombo_kandy = (
        db.query(TrainSchedule)
        .filter(
            TrainSchedule.train_id == train_pm4082.id,
            TrainSchedule.from_station == "Colombo",
            TrainSchedule.to_station == "Kandy",
            TrainSchedule.travel_date == target_date,
        )
        .first()
    )

    if not schedule_colombo_kandy:
        schedule_colombo_kandy = TrainSchedule(
            train_id=train_pm4082.id,
            from_station="Colombo",
            to_station="Kandy",
            travel_date=target_date,
            departure_time=time(7, 0),
            arrival_time=time(10, 15),
            first_class_capacity=40,
            second_class_capacity=120,
        )
        db.add(schedule_colombo_kandy)
        db.flush()

    # 4. Schedule for PM-4082 (dynamic future date for integration tests)
    future_date = date.today() + timedelta(days=30)
    schedule_future = (
        db.query(TrainSchedule)
        .filter(
            TrainSchedule.train_id == train_pm4082.id,
            TrainSchedule.from_station == "Colombo",
            TrainSchedule.to_station == "Kandy",
            TrainSchedule.travel_date == future_date,
        )
        .first()
    )

    if not schedule_future:
        schedule_future = TrainSchedule(
            train_id=train_pm4082.id,
            from_station="Colombo",
            to_station="Kandy",
            travel_date=future_date,
            departure_time=time(7, 0),
            arrival_time=time(10, 15),
            first_class_capacity=40,
            second_class_capacity=120,
        )
        db.add(schedule_future)
        db.flush()

    db.commit()

    return {
        "active_train": train_pm4082,
        "inactive_train": train_inact,
        "schedule": schedule_colombo_kandy,
        "schedule_future": schedule_future,
    }
