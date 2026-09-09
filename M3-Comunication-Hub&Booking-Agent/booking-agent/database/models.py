"""
database/models.py
------------------
SQLAlchemy 2.x ORM models for the Booking Agent.

Tables
------
- trains                : known train services
- train_schedules       : per-date schedule rows for each train
- bookings              : confirmed passenger bookings
- cancellation_requests : passenger-initiated cancellation cases
- audit_logs            : inter-agent message audit trail

Phase 1 scope
-------------
Schema definitions and relationships only.  No CRUD operations, no business
logic, no fare/policy calculations.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# ===========================================================================
# Status / category enums
# ===========================================================================

class BookingStatus(str, enum.Enum):
    """Lifecycle states for a booking row."""
    CONFIRMED        = "CONFIRMED"
    CANCELLED        = "CANCELLED"


class CancellationStatus(str, enum.Enum):
    """Lifecycle states for a cancellation-request row."""
    PENDING_ADMIN_REVIEW = "PENDING_ADMIN_REVIEW"
    APPROVED             = "APPROVED"
    REJECTED             = "REJECTED"


class AuditStatus(str, enum.Enum):
    """Possible audit-log statuses for an inter-agent message."""
    RECEIVED      = "RECEIVED"
    VALIDATED     = "VALIDATED"
    AUTHENTICATED = "AUTHENTICATED"
    ROUTED        = "ROUTED"
    REJECTED      = "REJECTED"
    FAILED        = "FAILED"


# ===========================================================================
# A. trains
# ===========================================================================

class Train(Base):
    """
    A registered train service.

    Relationships
    -------------
    schedules   : one-to-many -> TrainSchedule
    bookings    : one-to-many -> Booking
    """

    __tablename__ = "trains"

    id:         Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    train_id:   Mapped[str]  = mapped_column(String(50),  nullable=False, unique=True, index=True)
    train_name: Mapped[str]  = mapped_column(String(200), nullable=False)
    active:     Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    schedules: Mapped[list["TrainSchedule"]] = relationship(
        "TrainSchedule", back_populates="train", cascade="all, delete-orphan"
    )
    bookings: Mapped[list["Booking"]] = relationship(
        "Booking", back_populates="train"
    )

    def __repr__(self) -> str:
        return f"<Train id={self.id} train_id={self.train_id!r}>"


# ===========================================================================
# B. train_schedules
# ===========================================================================

class TrainSchedule(Base):
    """
    A single scheduled run of a train on a specific date.

    Relationships
    -------------
    train    : many-to-one -> Train
    bookings : one-to-many -> Booking
    """

    __tablename__ = "train_schedules"

    id:                    Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    train_id:              Mapped[int]  = mapped_column(
                               Integer, ForeignKey("trains.id", ondelete="CASCADE"), nullable=False, index=True
                           )
    from_station:          Mapped[str]  = mapped_column(String(200), nullable=False)
    to_station:            Mapped[str]  = mapped_column(String(200), nullable=False)
    travel_date:           Mapped[date] = mapped_column(Date, nullable=False)
    departure_time:        Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    arrival_time:          Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    first_class_capacity:  Mapped[int]  = mapped_column(Integer, nullable=False)
    second_class_capacity: Mapped[int]  = mapped_column(Integer, nullable=False)

    __table_args__ = (
        # Composite index: common query pattern is train + date
        Index("ix_schedules_train_date", "train_id", "travel_date"),
    )

    # Relationships
    train: Mapped["Train"] = relationship("Train", back_populates="schedules")
    bookings: Mapped[list["Booking"]] = relationship(
        "Booking", back_populates="schedule"
    )

    def __repr__(self) -> str:
        return (
            f"<TrainSchedule id={self.id} train_id={self.train_id}"
            f" date={self.travel_date}>"
        )


# ===========================================================================
# C. bookings
# ===========================================================================

class Booking(Base):
    """
    A confirmed passenger booking.

    Fare is stored as Numeric(10, 2) to avoid floating-point rounding errors.
    Default status is CONFIRMED because payment processing is outside the
    current Member C specification.

    Relationships
    -------------
    train                : many-to-one -> Train
    schedule             : many-to-one -> TrainSchedule
    cancellation_request : one-to-one  -> CancellationRequest (if raised)
    """

    __tablename__ = "bookings"

    id:                Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_reference: Mapped[str]            = mapped_column(String(50), nullable=False, unique=True, index=True)
    user_id:           Mapped[str]            = mapped_column(String(100), nullable=False, index=True)
    train_id:          Mapped[int]            = mapped_column(
                           Integer, ForeignKey("trains.id", ondelete="RESTRICT"), nullable=False, index=True
                       )
    schedule_id:       Mapped[int]            = mapped_column(
                           Integer, ForeignKey("train_schedules.id", ondelete="RESTRICT"), nullable=False
                       )
    from_station:      Mapped[str]            = mapped_column(String(200), nullable=False)
    to_station:        Mapped[str]            = mapped_column(String(200), nullable=False)
    travel_date:       Mapped[date]           = mapped_column(Date, nullable=False)
    seat_class:        Mapped[str]            = mapped_column(String(50), nullable=False)
    passenger_count:   Mapped[int]            = mapped_column(Integer, nullable=False)
    fare:              Mapped[Decimal]        = mapped_column(Numeric(10, 2), nullable=False)
    status:            Mapped[BookingStatus]  = mapped_column(
                           SAEnum(BookingStatus, name="booking_status"),
                           nullable=False,
                           default=BookingStatus.CONFIRMED,
                           server_default=BookingStatus.CONFIRMED.value,
                       )
    created_at:        Mapped[datetime]       = mapped_column(
                           DateTime(timezone=True), nullable=False, server_default=func.now()
                       )
    updated_at:        Mapped[datetime]       = mapped_column(
                           DateTime(timezone=True), nullable=False,
                           server_default=func.now(), onupdate=func.now()
                       )

    # Relationships
    train:    Mapped["Train"]         = relationship("Train",         back_populates="bookings")
    schedule: Mapped["TrainSchedule"] = relationship("TrainSchedule", back_populates="bookings")
    cancellation_request: Mapped["CancellationRequest | None"] = relationship(
        "CancellationRequest", back_populates="booking", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Booking id={self.id} ref={self.booking_reference!r} status={self.status}>"


# ===========================================================================
# D. cancellation_requests
# ===========================================================================

class CancellationRequest(Base):
    """
    A passenger-raised request to cancel a booking.

    Nullable AI-populated fields (reason_category, eligibility,
    suggested_refund, ai_summary) are intentionally left empty in Phase 1.
    They will be filled by the NLP/LLM component in a later phase.

    admin_decision, admin_reason, and reviewed_at are filled by the admin
    review workflow (also a later phase).

    Relationships
    -------------
    booking : many-to-one -> Booking
    """

    __tablename__ = "cancellation_requests"

    id:               Mapped[int]                 = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_reference:   Mapped[str]                 = mapped_column(String(50), nullable=False, unique=True, index=True)
    booking_id:       Mapped[int]                 = mapped_column(
                          Integer, ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
                      )
    reason:           Mapped[str]                 = mapped_column(Text, nullable=False)

    # --- Populated by NLP phase (nullable until then) ---
    reason_category:  Mapped[str | None]          = mapped_column(String(100), nullable=True)
    eligibility:      Mapped[str | None]          = mapped_column(String(50),  nullable=True)
    suggested_refund: Mapped[Decimal | None]      = mapped_column(Numeric(10, 2), nullable=True)
    ai_summary:       Mapped[str | None]          = mapped_column(Text, nullable=True)

    status:           Mapped[CancellationStatus]  = mapped_column(
                          SAEnum(CancellationStatus, name="cancellation_status"),
                          nullable=False,
                          default=CancellationStatus.PENDING_ADMIN_REVIEW,
                          server_default=CancellationStatus.PENDING_ADMIN_REVIEW.value,
                      )

    # --- Populated by admin review phase (nullable until then) ---
    admin_decision:   Mapped[str | None]          = mapped_column(String(50),  nullable=True)
    admin_reason:     Mapped[str | None]          = mapped_column(Text, nullable=True)
    reviewed_at:      Mapped[datetime | None]     = mapped_column(DateTime(timezone=True), nullable=True)

    created_at:       Mapped[datetime]            = mapped_column(
                          DateTime(timezone=True), nullable=False, server_default=func.now()
                      )

    # Relationship
    booking: Mapped["Booking"] = relationship("Booking", back_populates="cancellation_request")

    def __repr__(self) -> str:
        return (
            f"<CancellationRequest id={self.id} case={self.case_reference!r}"
            f" status={self.status}>"
        )


# ===========================================================================
# E. audit_logs
# ===========================================================================

class AuditLog(Base):
    """
    Immutable record of every inter-agent message processed by the Agent Hub.

    Rows are written by the audit service (implemented in a later phase).
    The model is defined here so the table is created with the rest of the
    schema.
    """

    __tablename__ = "audit_logs"

    id:             Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id:     Mapped[str]          = mapped_column(String(100), nullable=False, index=True)
    sender_agent:   Mapped[str]          = mapped_column(String(100), nullable=False)
    receiver_agent: Mapped[str]          = mapped_column(String(100), nullable=False)
    intent:         Mapped[str]          = mapped_column(String(100), nullable=False)
    status:         Mapped[AuditStatus]  = mapped_column(
                        SAEnum(AuditStatus, name="audit_status"), nullable=False
                    )
    error_message:  Mapped[str | None]   = mapped_column(Text, nullable=True)
    timestamp:      Mapped[datetime]     = mapped_column(
                        DateTime(timezone=True), nullable=False, server_default=func.now()
                    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} message_id={self.message_id!r}"
            f" status={self.status}>"
        )
