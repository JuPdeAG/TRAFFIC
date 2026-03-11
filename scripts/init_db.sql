-- Enable extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS road_segments (
    id              VARCHAR(100) PRIMARY KEY,
    pilot           VARCHAR(50) NOT NULL,
    name            VARCHAR(200),
    geom            GEOMETRY(LineString, 4326) NOT NULL,
    length_m        FLOAT,
    speed_limit_kmh SMALLINT,
    road_class      VARCHAR(50),
    lanes           SMALLINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_road_segments_geom ON road_segments USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_road_segments_pilot ON road_segments (pilot);

CREATE TABLE IF NOT EXISTS speed_baseline (
    id                  SERIAL PRIMARY KEY,
    segment_id          VARCHAR(100) NOT NULL REFERENCES road_segments(id),
    hour_of_day         SMALLINT NOT NULL CHECK (hour_of_day BETWEEN 0 AND 23),
    day_of_week         SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    local_hour_of_day   SMALLINT CHECK (local_hour_of_day BETWEEN 0 AND 23),
    local_day_of_week   SMALLINT CHECK (local_day_of_week BETWEEN 0 AND 6),
    timezone            VARCHAR(64) DEFAULT 'UTC',
    avg_speed_kmh       FLOAT NOT NULL,
    std_speed_kmh       FLOAT,
    sample_count        INTEGER NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (segment_id, hour_of_day, day_of_week)
);

CREATE TABLE IF NOT EXISTS incidents (
    id              SERIAL PRIMARY KEY,
    pilot           VARCHAR(50) NOT NULL,
    incident_type   VARCHAR(100) NOT NULL,
    severity        SMALLINT CHECK (severity BETWEEN 1 AND 5),
    status          VARCHAR(50) NOT NULL DEFAULT 'active',
    location_geom   GEOMETRY(Point, 4326),
    segment_id      VARCHAR(100) REFERENCES road_segments(id),
    description     TEXT,
    source          VARCHAR(100),
    external_id     VARCHAR(200),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_incidents_geom ON incidents USING GIST (location_geom);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents (status) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS road_assets (
    id              VARCHAR(100) PRIMARY KEY,
    pilot           VARCHAR(50) NOT NULL,
    asset_type      VARCHAR(100) NOT NULL,
    location_geom   GEOMETRY(Point, 4326),
    segment_id      VARCHAR(100) REFERENCES road_segments(id),
    installed_at    DATE,
    last_inspected  DATE,
    condition_score SMALLINT CHECK (condition_score BETWEEN 0 AND 100),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS damage_detections (
    id              SERIAL PRIMARY KEY,
    asset_id        VARCHAR(100) REFERENCES road_assets(id),
    camera_id       VARCHAR(100),
    defect_class    VARCHAR(10) NOT NULL,
    confidence      FLOAT NOT NULL,
    bbox_json       JSONB,
    s3_annotated_key VARCHAR(500),
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed        BOOLEAN NOT NULL DEFAULT FALSE,
    is_confirmed    BOOLEAN
);

CREATE TABLE IF NOT EXISTS maintenance_tickets (
    id              SERIAL PRIMARY KEY,
    asset_id        VARCHAR(100) NOT NULL REFERENCES road_assets(id),
    detection_id    INTEGER REFERENCES damage_detections(id),
    pilot           VARCHAR(50) NOT NULL,
    status          VARCHAR(50) NOT NULL DEFAULT 'open',
    priority        SMALLINT NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    title           VARCHAR(300) NOT NULL,
    description     TEXT,
    assigned_to     UUID,
    created_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(320) NOT NULL UNIQUE,
    name            VARCHAR(200),
    role            VARCHAR(50) NOT NULL DEFAULT 'viewer',
    pilot_scope     VARCHAR(100),
    password_hash   VARCHAR(200),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS vehicle_tracks (
    id              BIGSERIAL PRIMARY KEY,
    track_id        UUID NOT NULL DEFAULT gen_random_uuid(),
    camera_id       VARCHAR(100) NOT NULL,
    segment_id      VARCHAR(100) REFERENCES road_segments(id),
    vehicle_class   VARCHAR(50),
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    speed_kmh       FLOAT,
    direction       SMALLINT
);
CREATE INDEX IF NOT EXISTS idx_vehicle_tracks_observed ON vehicle_tracks (observed_at);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id              SERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id),
    endpoint        TEXT NOT NULL UNIQUE,
    p256dh          TEXT NOT NULL,
    auth            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);
