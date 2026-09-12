-- ===========================================================================
-- RailSense AI — Member C Supabase PostgreSQL Schema & Seed Script
-- Project Reference: qtdzbnporxwidrwwbraw
-- ===========================================================================

-- 1. Custom Enum Types
DO $$ BEGIN
    CREATE TYPE booking_status AS ENUM ('CONFIRMED', 'CANCELLED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE cancellation_status AS ENUM ('PENDING_ADMIN_REVIEW', 'APPROVED', 'REJECTED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE audit_status AS ENUM ('RECEIVED', 'VALIDATED', 'AUTHENTICATED', 'ROUTED', 'REJECTED', 'FAILED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 2. Table: trains
CREATE TABLE IF NOT EXISTS trains (
    id SERIAL PRIMARY KEY,
    train_id VARCHAR(50) NOT NULL UNIQUE,
    train_name VARCHAR(200) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS ix_trains_train_id ON trains (train_id);

-- 3. Table: train_schedules
CREATE TABLE IF NOT EXISTS train_schedules (
    id SERIAL PRIMARY KEY,
    train_id INTEGER NOT NULL REFERENCES trains (id) ON DELETE CASCADE,
    from_station VARCHAR(200) NOT NULL,
    to_station VARCHAR(200) NOT NULL,
    travel_date DATE NOT NULL,
    departure_time TIME WITHOUT TIME ZONE NOT NULL,
    arrival_time TIME WITHOUT TIME ZONE NOT NULL,
    first_class_capacity INTEGER NOT NULL,
    second_class_capacity INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_schedules_train_date ON train_schedules (train_id, travel_date);
CREATE INDEX IF NOT EXISTS ix_train_schedules_train_id ON train_schedules (train_id);

-- 4. Table: bookings
CREATE TABLE IF NOT EXISTS bookings (
    id SERIAL PRIMARY KEY,
    booking_reference VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,
    train_id INTEGER NOT NULL REFERENCES trains (id) ON DELETE RESTRICT,
    schedule_id INTEGER NOT NULL REFERENCES train_schedules (id) ON DELETE RESTRICT,
    from_station VARCHAR(200) NOT NULL,
    to_station VARCHAR(200) NOT NULL,
    travel_date DATE NOT NULL,
    seat_class VARCHAR(50) NOT NULL,
    passenger_count INTEGER NOT NULL,
    fare NUMERIC(10, 2) NOT NULL,
    status booking_status NOT NULL DEFAULT 'CONFIRMED',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bookings_booking_reference ON bookings (booking_reference);
CREATE INDEX IF NOT EXISTS ix_bookings_user_id ON bookings (user_id);
CREATE INDEX IF NOT EXISTS ix_bookings_train_id ON bookings (train_id);

-- 5. Table: cancellation_requests
CREATE TABLE IF NOT EXISTS cancellation_requests (
    id SERIAL PRIMARY KEY,
    case_reference VARCHAR(50) NOT NULL UNIQUE,
    booking_id INTEGER NOT NULL UNIQUE REFERENCES bookings (id) ON DELETE RESTRICT,
    reason TEXT NOT NULL,
    reason_category VARCHAR(100),
    eligibility VARCHAR(50),
    suggested_refund NUMERIC(10, 2),
    ai_summary TEXT,
    status cancellation_status NOT NULL DEFAULT 'PENDING_ADMIN_REVIEW',
    admin_decision VARCHAR(50),
    admin_reason TEXT,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cancellation_requests_case_reference ON cancellation_requests (case_reference);
CREATE INDEX IF NOT EXISTS ix_cancellation_requests_booking_id ON cancellation_requests (booking_id);

-- 6. Table: audit_logs
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(100) NOT NULL,
    sender_agent VARCHAR(100) NOT NULL,
    receiver_agent VARCHAR(100) NOT NULL,
    intent VARCHAR(100) NOT NULL,
    status audit_status NOT NULL,
    error_message TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_logs_message_id ON audit_logs (message_id);

-- 7. Table: passengers
CREATE TABLE IF NOT EXISTS passengers (
    id SERIAL PRIMARY KEY,
    nic_hash VARCHAR(64) NOT NULL UNIQUE,
    nic_masked VARCHAR(30) NOT NULL,
    full_name VARCHAR(150),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_passengers_nic_hash ON passengers (nic_hash);

-- 8. Table: booking_passengers
CREATE TABLE IF NOT EXISTS booking_passengers (
    id SERIAL PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES bookings (id) ON DELETE CASCADE,
    passenger_id INTEGER NOT NULL REFERENCES passengers (id) ON DELETE RESTRICT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_booking_passengers_booking_id ON booking_passengers (booking_id);
CREATE INDEX IF NOT EXISTS ix_booking_passengers_passenger_id ON booking_passengers (passenger_id);

-- 9. Table: fraud_reviews
DO $$ BEGIN
    CREATE TYPE fraud_review_status AS ENUM ('PENDING_REVIEW', 'APPROVED', 'REJECTED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS fraud_reviews (
    id SERIAL PRIMARY KEY,
    case_reference VARCHAR(50) NOT NULL UNIQUE,
    request_reference VARCHAR(100),
    booking_payload TEXT NOT NULL,
    primary_nic_hash VARCHAR(64) NOT NULL,
    risk_score NUMERIC(5, 4) NOT NULL,
    risk_level VARCHAR(20) NOT NULL,
    recommended_action VARCHAR(50) NOT NULL,
    reasons TEXT NOT NULL,
    status fraud_review_status NOT NULL DEFAULT 'PENDING_REVIEW',
    admin_decision VARCHAR(50),
    admin_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    reviewed_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS ix_fraud_reviews_case_reference ON fraud_reviews (case_reference);
CREATE INDEX IF NOT EXISTS ix_fraud_reviews_primary_nic_hash ON fraud_reviews (primary_nic_hash);
CREATE INDEX IF NOT EXISTS ix_fraud_reviews_status ON fraud_reviews (status);

-- 10. Seed Data
INSERT INTO trains (train_id, train_name, active)
VALUES 
    ('PM-4082', 'Intercity Express', true),
    ('INACT-9999', 'Maintenance Railcar', false)
ON CONFLICT (train_id) DO NOTHING;

INSERT INTO train_schedules (
    train_id,
    from_station,
    to_station,
    travel_date,
    departure_time,
    arrival_time,
    first_class_capacity,
    second_class_capacity
)
SELECT 
    t.id,
    'Colombo',
    'Kandy',
    '2026-12-03'::DATE,
    '07:00:00'::TIME,
    '10:15:00'::TIME,
    40,
    120
FROM trains t
WHERE t.train_id = 'PM-4082'
ON CONFLICT DO NOTHING;

-- ===========================================================================
-- 8. Cancellation Policy Embeddings & Vector Search (pgvector)
-- ===========================================================================
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS cancellation_policy_embeddings (
    id SERIAL PRIMARY KEY,
    document VARCHAR(100) NOT NULL,
    document_id VARCHAR(50) NOT NULL,
    section VARCHAR(200) NOT NULL,
    citation VARCHAR(250) NOT NULL,
    content TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_cancellation_policy_embeddings_embedding
ON cancellation_policy_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE OR REPLACE FUNCTION match_cancellation_policies (
    query_embedding vector(384),
    match_count int DEFAULT 3
)
RETURNS TABLE (
    id int,
    document varchar,
    document_id varchar,
    section varchar,
    citation varchar,
    content text,
    similarity double precision
)
LANGUAGE sql STABLE
AS $$
    SELECT
        p.id,
        p.document,
        p.document_id,
        p.section,
        p.citation,
        p.content,
        1 - (p.embedding <=> query_embedding) AS similarity
    FROM cancellation_policy_embeddings p
    ORDER BY p.embedding <=> query_embedding
    LIMIT LEAST(match_count, 10);
$$;

