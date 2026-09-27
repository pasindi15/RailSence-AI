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
import json
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
    HELD                 = "HELD"
    PENDING_FRAUD_REVIEW = "PENDING_FRAUD_REVIEW"
    CONFIRMED            = "CONFIRMED"
    CANCELLED            = "CANCELLED"
    EXPIRED              = "EXPIRED"
    REJECTED             = "REJECTED"


class HoldStatus(str, enum.Enum):
    """Lifecycle states for a temporary seat hold."""
    ACTIVE    = "ACTIVE"
    CONFIRMED = "CONFIRMED"
    RELEASED  = "RELEASED"
    EXPIRED   = "EXPIRED"


class WaitingListStatus(str, enum.Enum):
    """Lifecycle states for a waiting-list queue entry."""
    WAITING   = "WAITING"
    OFFERED   = "OFFERED"
    ALLOCATED = "ALLOCATED"
    ACCEPTED  = "ACCEPTED"
    EXPIRED   = "EXPIRED"
    CANCELLED = "CANCELLED"


class IdempotencyStatus(str, enum.Enum):
    """Processing state for an idempotent mutation operation."""
    PROCESSING = "PROCESSING"
    COMMITTED  = "COMMITTED"
    COMPLETED  = "COMPLETED"
    CONFIRMED  = "CONFIRMED"
    FAILED     = "FAILED"


class InvestigationLabel(str, enum.Enum):
    """Ground truth feedback label assigned by human investigator."""
    UNKNOWN         = "UNKNOWN"
    LEGITIMATE      = "LEGITIMATE"
    FALSE_POSITIVE  = "FALSE_POSITIVE"
    CONFIRMED_FRAUD = "CONFIRMED_FRAUD"


class CancellationStatus(str, enum.Enum):
    """Lifecycle states for a cancellation-request row."""
    PENDING_ADMIN_REVIEW = "PENDING_ADMIN_REVIEW"
    APPROVED             = "APPROVED"
    REJECTED             = "REJECTED"


class FraudReviewStatus(str, enum.Enum):
    """Lifecycle states for a fraud review case."""
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED       = "APPROVED"
    REJECTED       = "REJECTED"


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

    id:                 Mapped[int]       = mapped_column(Integer, primary_key=True, autoincrement=True)
    train_id:           Mapped[str]       = mapped_column(String(50),  nullable=False, unique=True, index=True)
    train_name:         Mapped[str]       = mapped_column(String(200), nullable=False)
    active:             Mapped[bool]      = mapped_column(Boolean, nullable=False, default=True)
    # Shared canonical fields — populated from the shared Supabase trains table.
    # NULL means the column is not yet present in the DB schema; always check before use.
    maintenance_status:  Mapped[str | None] = mapped_column(String(100), nullable=True)
    route:               Mapped[str | None] = mapped_column(String(500), nullable=True)
    origin_station:      Mapped[str | None] = mapped_column(String(200), nullable=True)
    destination_station: Mapped[str | None] = mapped_column(String(200), nullable=True)
    train_type:          Mapped[str | None] = mapped_column(String(100), nullable=True)

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
    A single scheduled run of a train on a specific date (a dated journey).

    Relationships
    -------------
    train    : many-to-one -> Train
    bookings : one-to-many -> Booking
    """

    __tablename__ = "train_schedules"

    id:                    Mapped[int]         = mapped_column(Integer, primary_key=True, autoincrement=True)
    train_id:              Mapped[int]         = mapped_column(
                               Integer, ForeignKey("trains.id", ondelete="CASCADE"), nullable=False, index=True
                           )
    from_station:          Mapped[str]         = mapped_column(String(200), nullable=False)
    to_station:            Mapped[str]         = mapped_column(String(200), nullable=False)
    travel_date:           Mapped[date]        = mapped_column(Date, nullable=False)
    departure_time:        Mapped[time]        = mapped_column(Time(timezone=False), nullable=False)
    arrival_time:          Mapped[time]        = mapped_column(Time(timezone=False), nullable=False)
    first_class_capacity:  Mapped[int]         = mapped_column(Integer, nullable=False)
    second_class_capacity: Mapped[int]         = mapped_column(Integer, nullable=False)
    service_status:        Mapped[str]         = mapped_column(
                               String(50), nullable=False, default="SCHEDULED", server_default="SCHEDULED"
                           )
    service_id:            Mapped[str | None]  = mapped_column(String(100), nullable=True, index=True)
    arrival_date:          Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        # Composite index: common query pattern is train + date
        Index("ix_schedules_train_date", "train_id", "travel_date"),
        # Unique identity constraint: prevents duplicate dated journeys under concurrent searches
        Index("ix_schedules_identity", "train_id", "travel_date", "from_station", "to_station", unique=True),
        Index("ix_schedules_service_date", "service_id", "travel_date"),
    )

    # Relationships
    train: Mapped["Train"] = relationship("Train", back_populates="schedules")
    bookings: Mapped[list["Booking"]] = relationship(
        "Booking", back_populates="schedule"
    )

    def __repr__(self) -> str:
        return (
            f"<TrainSchedule id={self.id} train_id={self.train_id}"
            f" date={self.travel_date} status={self.service_status}>"
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
    ticket_token:      Mapped[str | None]     = mapped_column(String(64), nullable=True, unique=True, index=True)
    hold_id:           Mapped[int | None]     = mapped_column(Integer, nullable=True, index=True)
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
    passenger_email:   Mapped[str | None]     = mapped_column(String(255), nullable=True)
    passenger_phone:   Mapped[str | None]     = mapped_column(String(32), nullable=True)
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
    booking_passengers: Mapped[list["BookingPassenger"]] = relationship(
        "BookingPassenger", back_populates="booking", cascade="all, delete-orphan"
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
    correlation_id: Mapped[str | None]   = mapped_column(String(100), nullable=True, index=True)
    sender_agent:   Mapped[str]          = mapped_column(String(100), nullable=False)
    receiver_agent: Mapped[str]          = mapped_column(String(100), nullable=False)
    intent:         Mapped[str]          = mapped_column(String(100), nullable=False)
    status:         Mapped[AuditStatus]  = mapped_column(
                        SAEnum(AuditStatus, name="audit_status"), nullable=False
                    )
    error_message:  Mapped[str | None]   = mapped_column(Text, nullable=True)
    duration_ms:    Mapped[int | None]   = mapped_column(Integer, nullable=True)
    retry_count:    Mapped[int]          = mapped_column(Integer, nullable=False, default=0, server_default="0")
    timestamp:      Mapped[datetime]     = mapped_column(
                        DateTime(timezone=True), nullable=False, server_default=func.now()
                    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} message_id={self.message_id!r}"
            f" status={self.status}>"
        )


# ===========================================================================
# F. passengers
# ===========================================================================

class Passenger(Base):
    """
    Normalized passenger identity, uniquely identified by deterministic HMAC-SHA256 of NIC.
    Allows the same passenger to book multiple legitimate journeys over time.
    """
    __tablename__ = "passengers"

    id:         Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    nic_hash:   Mapped[str]               = mapped_column(String(64), nullable=False, unique=True, index=True)
    nic_masked: Mapped[str]               = mapped_column(String(30), nullable=False)
    full_name:  Mapped[str | None]        = mapped_column(String(150), nullable=True)
    phone:      Mapped[str | None]        = mapped_column(String(32), nullable=True)
    dob:        Mapped[date | None]       = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime]          = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    booking_passengers: Mapped[list["BookingPassenger"]] = relationship(
        "BookingPassenger", back_populates="passenger"
    )

    def __repr__(self) -> str:
        return f"<Passenger id={self.id} masked={self.nic_masked!r}>"


# ===========================================================================
# G. booking_passengers
# ===========================================================================

class BookingPassenger(Base):
    """
    Association table linking a Booking to each individual Passenger.
    Enforces one NIC per passenger within and across bookings.
    """
    __tablename__ = "booking_passengers"

    id:           Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_id:   Mapped[int]             = mapped_column(
        Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    passenger_id: Mapped[int]             = mapped_column(
        Integer, ForeignKey("passengers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at:   Mapped[datetime]        = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    booking:   Mapped["Booking"]          = relationship("Booking", back_populates="booking_passengers")
    passenger: Mapped["Passenger"]        = relationship("Passenger", back_populates="booking_passengers")

    def __repr__(self) -> str:
        return f"<BookingPassenger id={self.id} booking_id={self.booking_id} passenger_id={self.passenger_id}>"


# ===========================================================================
# H. fraud_reviews
# ===========================================================================

class FraudReview(Base):
    """
    Record of a booking request flagged for human administrative review by ML/anomaly detection.
    """
    __tablename__ = "fraud_reviews"

    id:                  Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_reference:      Mapped[str]               = mapped_column(String(50), nullable=False, unique=True, index=True)
    request_reference:   Mapped[str | None]        = mapped_column(String(100), nullable=True)
    booking_payload:     Mapped[str]               = mapped_column(Text, nullable=False)
    primary_nic_hash:    Mapped[str]               = mapped_column(String(64), nullable=False, index=True)
    risk_score:          Mapped[Decimal]           = mapped_column(Numeric(5, 4), nullable=False)
    risk_level:          Mapped[str]               = mapped_column(String(20), nullable=False)
    recommended_action:  Mapped[str]               = mapped_column(String(50), nullable=False)
    reasons:             Mapped[str]               = mapped_column(Text, nullable=False)
    status:              Mapped[FraudReviewStatus] = mapped_column(
        SAEnum(FraudReviewStatus, name="fraud_review_status"),
        nullable=False,
        default=FraudReviewStatus.PENDING_REVIEW,
        server_default=FraudReviewStatus.PENDING_REVIEW.value,
    )
    admin_decision:      Mapped[str | None]        = mapped_column(String(50), nullable=True)
    admin_reason:        Mapped[str | None]        = mapped_column(Text, nullable=True)
    created_at:          Mapped[datetime]          = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at:         Mapped[datetime | None]   = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<FraudReview id={self.id} case={self.case_reference!r} status={self.status}>"


# ===========================================================================
# I. seat_holds (Server-controlled expiring reservation holds)
# ===========================================================================

class SeatHold(Base):
    """
    Temporary seat hold record with server-controlled expiration.
    Guarantees that a seat is held while booking/payment/review completes,
    and automatically releases seats once expired.
    """
    __tablename__ = "seat_holds"

    id:           Mapped[int]        = mapped_column(Integer, primary_key=True, autoincrement=True)
    hold_token:   Mapped[str]        = mapped_column(String(64), nullable=False, unique=True, index=True)
    schedule_id:  Mapped[int]        = mapped_column(
        Integer, ForeignKey("train_schedules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seat_class:   Mapped[str]        = mapped_column(String(50), nullable=False)
    seat_count:   Mapped[int]        = mapped_column(Integer, nullable=False)
    nic_hashes:   Mapped[str]        = mapped_column(Text, nullable=False)  # JSON array of hashed NICs
    user_id:      Mapped[str]        = mapped_column(String(100), nullable=False, index=True)
    status:       Mapped[HoldStatus] = mapped_column(
        SAEnum(HoldStatus, name="hold_status"),
        nullable=False,
        default=HoldStatus.ACTIVE,
        server_default=HoldStatus.ACTIVE.value,
    )
    expires_at:   Mapped[datetime]   = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at:   Mapped[datetime]   = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def is_active(self) -> bool:
        from datetime import datetime, timezone
        return self.status == HoldStatus.ACTIVE and self.expires_at > datetime.now(timezone.utc)

    def __repr__(self) -> str:
        return f"<SeatHold id={self.id} token={self.hold_token!r} status={self.status}>"


# ===========================================================================
# J. waiting_list_entries (Deterministic FIFO Queue)
# ===========================================================================

class WaitingListEntry(Base):
    """
    Deterministic FIFO waiting list entry for high-demand train schedules.
    On seat release (cancellation, expiry, rejection), eligible requests
    receive a time-limited offer.
    """
    __tablename__ = "waiting_list_entries"

    id:                Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_token:       Mapped[str]               = mapped_column(String(64), nullable=False, unique=True, index=True)
    schedule_id:       Mapped[int]               = mapped_column(
        Integer, ForeignKey("train_schedules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    train_id:          Mapped[int]               = mapped_column(
        Integer, ForeignKey("trains.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seat_class:        Mapped[str]               = mapped_column(String(50), nullable=False)
    passenger_count:   Mapped[int]               = mapped_column(Integer, nullable=False)
    passenger_email:   Mapped[str | None]        = mapped_column(String(255), nullable=True)
    user_id:           Mapped[str]               = mapped_column(String(100), nullable=False, index=True)
    passenger_payload: Mapped[str]               = mapped_column(Text, nullable=False)  # JSON passenger details
    status:            Mapped[WaitingListStatus] = mapped_column(
        SAEnum(WaitingListStatus, name="waiting_list_status"),
        nullable=False,
        default=WaitingListStatus.WAITING,
        server_default=WaitingListStatus.WAITING.value,
    )
    offer_expires_at:  Mapped[datetime | None]   = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:        Mapped[datetime]          = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    def __repr__(self) -> str:
        return f"<WaitingListEntry id={self.id} token={self.queue_token!r} status={self.status}>"


# ===========================================================================
# K. idempotency_records (Atomic Mutation Deduplication)
# ===========================================================================

class IdempotencyRecord(Base):
    """
    Persists business mutation idempotency state.
    Guarantees that replayed requests with the same key return identical results
    without executing duplicate booking, cancellation, or hold mutations.
    """
    __tablename__ = "idempotency_records"

    id:               Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key:  Mapped[str]               = mapped_column(String(100), nullable=False, index=True)
    actor:            Mapped[str]               = mapped_column(String(100), nullable=False, index=True)
    operation:        Mapped[str]               = mapped_column(String(50), nullable=False)
    request_hash:     Mapped[str]               = mapped_column(String(64), nullable=False)
    status:           Mapped[IdempotencyStatus] = mapped_column(
        SAEnum(IdempotencyStatus, name="idempotency_status"),
        nullable=False,
        default=IdempotencyStatus.PROCESSING,
        server_default=IdempotencyStatus.PROCESSING.value,
    )
    response_payload: Mapped[str | None]        = mapped_column(Text, nullable=True)
    created_at:       Mapped[datetime]          = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at:       Mapped[datetime | None]   = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_idempotency_actor_key", "actor", "operation", "idempotency_key", unique=True),
    )

    @property
    def payload_hash(self) -> str:
        return self.request_hash

    @property
    def booking_reference(self) -> str | None:
        if not self.response_payload:
            return None
        try:
            d = json.loads(self.response_payload)
            return d.get("booking_reference")
        except Exception:
            return None

    def __repr__(self) -> str:
        return f"<IdempotencyRecord id={self.id} key={self.idempotency_key!r} status={self.status}>"


# ===========================================================================
# L. fraud_investigation_labels (Ground Truth Reviewer Attribution)
# ===========================================================================

class FraudInvestigationLabel(Base):
    """
    Independent ground-truth investigation label assigned by human reviewer.
    Allows distinguishing between operational approval and model accuracy ground truth.
    """
    __tablename__ = "fraud_investigation_labels"

    id:              Mapped[int]                = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_reference:  Mapped[str]                = mapped_column(String(50), nullable=False, index=True)
    label:           Mapped[InvestigationLabel] = mapped_column(
        SAEnum(InvestigationLabel, name="investigation_label"), nullable=False, default=InvestigationLabel.CONFIRMED_FRAUD
    )
    evidence_notes:  Mapped[str | None]         = mapped_column(Text, nullable=True)
    reviewer_id:     Mapped[str]                = mapped_column(String(100), nullable=False, default="admin")
    created_at:      Mapped[datetime]           = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __init__(self, **kwargs: Any) -> None:
        if "true_label" in kwargs and "label" not in kwargs:
            tl = kwargs.pop("true_label")
            if isinstance(tl, str):
                kwargs["label"] = InvestigationLabel(tl.upper()) if tl.upper() in InvestigationLabel._value2member_map_ else InvestigationLabel.CONFIRMED_FRAUD
            else:
                kwargs["label"] = tl
        if "reviewer_notes" in kwargs and "evidence_notes" not in kwargs:
            kwargs["evidence_notes"] = kwargs.pop("reviewer_notes")
        if "reviewer_id" not in kwargs:
            kwargs["reviewer_id"] = "admin"
        kwargs.pop("primary_nic_hash", None)
        super().__init__(**kwargs)

    @property
    def true_label(self) -> str:
        return self.label.value if hasattr(self.label, "value") else str(self.label)

    @property
    def reviewer_notes(self) -> str | None:
        return self.evidence_notes

    def __repr__(self) -> str:
        return f"<FraudInvestigationLabel id={self.id} case={self.case_reference!r} label={self.label}>"



