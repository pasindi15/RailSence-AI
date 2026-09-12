-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.operations_history (
  record_id uuid NOT NULL,
  route text NOT NULL,
  station text NOT NULL,
  train_id text NOT NULL,
  scheduled_time timestamp with time zone NOT NULL,
  actual_time timestamp with time zone NOT NULL,
  weather text NOT NULL,
  day_type text NOT NULL,
  incident_type text NOT NULL,
  incident_note text NOT NULL DEFAULT ''::text,
  delay_minutes double precision NOT NULL CHECK (delay_minutes >= '-2'::integer::double precision),
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT operations_history_pkey PRIMARY KEY (record_id)
);
CREATE TABLE public.incident_embeddings (
  record_id uuid NOT NULL,
  route text NOT NULL,
  station text NOT NULL,
  incident_type text NOT NULL,
  delay_minutes double precision NOT NULL,
  incident_note text NOT NULL,
  embedding USER-DEFINED NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT incident_embeddings_pkey PRIMARY KEY (record_id),
  CONSTRAINT incident_embeddings_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.operations_history(record_id)
);
CREATE TABLE public.audit_events (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  action text NOT NULL,
  agent_name text NOT NULL DEFAULT 'operations-agent'::text,
  sender_agent text,
  receiver_agent text,
  route text,
  train_id text,
  predicted_delay_minutes double precision,
  model_version text,
  classified_type text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT audit_events_pkey PRIMARY KEY (id)
);
CREATE TABLE public.operational_events (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  event_type text NOT NULL,
  sender_agent text NOT NULL DEFAULT 'operations-agent'::text,
  route text,
  train_id text,
  severity text NOT NULL DEFAULT 'warning'::text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  published_destinations ARRAY NOT NULL DEFAULT '{}'::text[],
  CONSTRAINT operational_events_pkey PRIMARY KEY (id)
);
CREATE TABLE public.operation_entities (
  id text NOT NULL,
  entity_type text NOT NULL,
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT operation_entities_pkey PRIMARY KEY (id)
);
CREATE TABLE public.incident_reports (
  incident_id uuid NOT NULL DEFAULT gen_random_uuid(),
  train_id text,
  station text,
  raw_text text,
  summary text,
  classified_type text,
  nlp_method text,
  review_status text DEFAULT 'pending'::text,
  reviewed_by text,
  reviewed_at double precision,
  received_at timestamp with time zone DEFAULT now(),
  CONSTRAINT incident_reports_pkey PRIMARY KEY (incident_id)
);
CREATE TABLE public.model_training_runs (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  triggered_by text,
  returncode integer,
  metrics jsonb,
  action text DEFAULT 'retrain'::text,
  restored_from text,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT model_training_runs_pkey PRIMARY KEY (id)
);
CREATE TABLE public.admin_config (
  key text NOT NULL,
  value jsonb,
  CONSTRAINT admin_config_pkey PRIMARY KEY (key)
);
CREATE TABLE public.admin_users (
  username text NOT NULL,
  password_hash text NOT NULL,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT admin_users_pkey PRIMARY KEY (username)
);
CREATE TABLE public.assets_history (
  record_id text NOT NULL,
  asset_id text NOT NULL,
  asset_type text NOT NULL,
  station text,
  route text,
  last_service_date date,
  days_since_service integer,
  fault_type text,
  fault_count_30d integer DEFAULT 0,
  health_score numeric,
  health_status text CHECK (health_status = ANY (ARRAY['GREEN'::text, 'AMBER'::text, 'RED'::text])),
  technician_note text,
  recommended_action text,
  temperature_celsius numeric,
  vibration_level numeric,
  oil_pressure_bar numeric,
  fuel_efficiency_pct numeric,
  axle_temp_celsius numeric,
  wheel_profile_mm numeric,
  pad_thickness_mm numeric,
  brake_cylinder_pressure_bar numeric,
  stopping_distance_m numeric,
  response_time_ms numeric,
  voltage_output_v numeric,
  contact_resistance_ohm numeric,
  rail_wear_mm numeric,
  gauge_deviation_mm numeric,
  ballast_void_pct numeric,
  motor_current_a numeric,
  cycle_time_seconds numeric,
  sensor_reliability_pct numeric,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT assets_history_pkey PRIMARY KEY (record_id)
);
CREATE TABLE public.manual_embeddings (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  section_id text NOT NULL UNIQUE,
  manual text NOT NULL,
  section_title text NOT NULL,
  content text NOT NULL,
  source_file text NOT NULL,
  embedding USER-DEFINED,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT manual_embeddings_pkey PRIMARY KEY (id)
);
CREATE TABLE public.trains (
  id integer NOT NULL DEFAULT nextval('trains_id_seq'::regclass),
  train_id character varying NOT NULL,
  train_name character varying NOT NULL,
  active boolean NOT NULL,
  CONSTRAINT trains_pkey PRIMARY KEY (id)
);
CREATE TABLE public.audit_logs (
  id integer NOT NULL DEFAULT nextval('audit_logs_id_seq'::regclass),
  message_id character varying NOT NULL,
  sender_agent character varying NOT NULL,
  receiver_agent character varying NOT NULL,
  intent character varying NOT NULL,
  status USER-DEFINED NOT NULL,
  error_message text,
  timestamp timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT audit_logs_pkey PRIMARY KEY (id)
);
CREATE TABLE public.train_schedules (
  id integer NOT NULL DEFAULT nextval('train_schedules_id_seq'::regclass),
  train_id integer NOT NULL,
  from_station character varying NOT NULL,
  to_station character varying NOT NULL,
  travel_date date NOT NULL,
  departure_time time without time zone NOT NULL,
  arrival_time time without time zone NOT NULL,
  first_class_capacity integer NOT NULL,
  second_class_capacity integer NOT NULL,
  CONSTRAINT train_schedules_pkey PRIMARY KEY (id),
  CONSTRAINT train_schedules_train_id_fkey FOREIGN KEY (train_id) REFERENCES public.trains(id)
);
CREATE TABLE public.bookings (
  id integer NOT NULL DEFAULT nextval('bookings_id_seq'::regclass),
  booking_reference character varying NOT NULL,
  user_id character varying NOT NULL,
  train_id integer NOT NULL,
  schedule_id integer NOT NULL,
  from_station character varying NOT NULL,
  to_station character varying NOT NULL,
  travel_date date NOT NULL,
  seat_class character varying NOT NULL,
  passenger_count integer NOT NULL,
  fare numeric NOT NULL,
  status USER-DEFINED NOT NULL DEFAULT 'CONFIRMED'::booking_status,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT bookings_pkey PRIMARY KEY (id),
  CONSTRAINT bookings_train_id_fkey FOREIGN KEY (train_id) REFERENCES public.trains(id),
  CONSTRAINT bookings_schedule_id_fkey FOREIGN KEY (schedule_id) REFERENCES public.train_schedules(id)
);
CREATE TABLE public.cancellation_requests (
  id integer NOT NULL DEFAULT nextval('cancellation_requests_id_seq'::regclass),
  case_reference character varying NOT NULL,
  booking_id integer NOT NULL,
  reason text NOT NULL,
  reason_category character varying,
  eligibility character varying,
  suggested_refund numeric,
  ai_summary text,
  status USER-DEFINED NOT NULL DEFAULT 'PENDING_ADMIN_REVIEW'::cancellation_status,
  admin_decision character varying,
  admin_reason text,
  reviewed_at timestamp with time zone,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT cancellation_requests_pkey PRIMARY KEY (id),
  CONSTRAINT cancellation_requests_booking_id_fkey FOREIGN KEY (booking_id) REFERENCES public.bookings(id)
);