-- ============================================ 
-- SkySentinel Database Schema
-- Phase 2: Historical Tracking & Anomalies
-- ============================================ 

-- Enable PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================ 
-- Reference Data: Airports
-- ============================================ 

CREATE TABLE IF NOT EXISTS airports (
    code VARCHAR(4) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    type VARCHAR(20) NOT NULL DEFAULT 'major',  -- major, regional, general_aviation
    geom GEOGRAPHY(GEOMETRY, 4326) NOT NULL,
    runway_heading_primary FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_airports_geom ON airports USING GIST(geom);

-- Seed NYC area airports
INSERT INTO airports (code, name, type, geom) VALUES
('JFK', 'John F. Kennedy International', 'major', 
 ST_GeomFromText('POLYGON((-73.82 40.62, -73.75 40.62, -73.75 40.67, -73.82 40.67, -73.82 40.62))', 4326)),
('LGA', 'LaGuardia', 'major',
 ST_Buffer(ST_GeomFromText('POINT(-73.8740 40.7769)', 4326)::geography, 3000)::geometry),
('EWR', 'Newark Liberty International', 'major',
 ST_Buffer(ST_GeomFromText('POINT(-74.1745 40.6895)', 4326)::geography, 5000)::geometry),
('TEB', 'Teterboro', 'general_aviation',
 ST_Buffer(ST_GeomFromText('POINT(-74.0608 40.8501)', 4326)::geography, 2000)::geometry),
('HPN', 'Westchester County', 'regional',
 ST_Buffer(ST_GeomFromText('POINT(-73.7076 41.0670)', 4326)::geography, 2000)::geometry)
ON CONFLICT (code) DO NOTHING;

-- ============================================ 
-- Current Flight State
-- ============================================ 

CREATE TABLE IF NOT EXISTS flights_current (
    icao24 VARCHAR(6) PRIMARY KEY,
    callsign VARCHAR(8),
    position GEOGRAPHY(POINT, 4326) NOT NULL,
    altitude_m DOUBLE PRECISION,
    altitude_m_smoothed DOUBLE PRECISION,
    geo_altitude_m DOUBLE PRECISION,
    heading_deg DOUBLE PRECISION,
    velocity_mps DOUBLE PRECISION,
    vertical_rate_mps DOUBLE PRECISION,
    vertical_rate_mps_smoothed DOUBLE PRECISION,
    on_ground BOOLEAN DEFAULT FALSE,
    squawk VARCHAR(4),
    status VARCHAR(30) DEFAULT 'NORMAL',
    flight_phase VARCHAR(20) DEFAULT 'UNKNOWN',  -- GROUND, TAKEOFF, DEPARTURE, EN_ROUTE, APPROACH, LANDING
    near_airport VARCHAR(4),
    last_contact_unix BIGINT,
    last_seen TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_flights_current_last_seen ON flights_current(last_seen);
CREATE INDEX idx_flights_current_status ON flights_current(status) WHERE status != 'NORMAL';
CREATE INDEX idx_flights_current_position ON flights_current USING GIST(position);

-- ============================================ 
-- Historical Positions
-- ============================================ 

CREATE TABLE IF NOT EXISTS flights_history (
    id BIGSERIAL,
    icao24 VARCHAR(6) NOT NULL,
    callsign VARCHAR(8),
    position GEOGRAPHY(POINT, 4326) NOT NULL,
    altitude_m DOUBLE PRECISION,
    altitude_m_smoothed DOUBLE PRECISION,
    heading_deg DOUBLE PRECISION,
    velocity_mps DOUBLE PRECISION,
    vertical_rate_mps DOUBLE PRECISION,
    on_ground BOOLEAN,
    flight_phase VARCHAR(20),
    recorded_at TIMESTAMPTZ NOT NULL,
    
    PRIMARY KEY (id, recorded_at)
) PARTITION BY RANGE (recorded_at);

-- Create default partition (for MVP; use pg_partman in production)
CREATE TABLE IF NOT EXISTS flights_history_default 
    PARTITION OF flights_history DEFAULT;

-- Create today's partition
DO $$
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS flights_history_%s PARTITION OF flights_history 
         FOR VALUES FROM (%L) TO (%L)',
        to_char(NOW(), 'YYYYMMDD'),
        date_trunc('day', NOW()),
        date_trunc('day', NOW()) + interval '1 day'
    );
EXCEPTION WHEN duplicate_table THEN
    NULL;
END $$;

CREATE INDEX idx_flights_history_icao24_time ON flights_history(icao24, recorded_at DESC);
CREATE INDEX idx_flights_history_recorded_at ON flights_history(recorded_at DESC);

-- ============================================ 
-- Anomalies
-- ============================================ 

CREATE TABLE IF NOT EXISTS anomalies (
    id BIGSERIAL PRIMARY KEY,
    icao24 VARCHAR(6) NOT NULL,
    callsign VARCHAR(8),
    anomaly_type VARCHAR(30) NOT NULL,
    severity VARCHAR(10) NOT NULL,
    details JSONB,
    position GEOGRAPHY(POINT, 4326),
    altitude_m DOUBLE PRECISION,
    near_airport VARCHAR(4),
    detected_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_anomalies_icao24 ON anomalies(icao24);
CREATE INDEX idx_anomalies_detected_at ON anomalies(detected_at DESC);
CREATE INDEX idx_anomalies_type ON anomalies(anomaly_type);
CREATE INDEX idx_anomalies_active ON anomalies(detected_at DESC) WHERE resolved_at IS NULL;

-- ============================================ 
-- Cleanup Functions
-- ============================================ 

CREATE OR REPLACE FUNCTION cleanup_stale_flights(stale_threshold INTERVAL DEFAULT '2 minutes')
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM flights_current 
    WHERE last_seen < NOW() - stale_threshold;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION cleanup_old_history(retention INTERVAL DEFAULT '24 hours')
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM flights_history 
    WHERE recorded_at < NOW() - retention;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION cleanup_old_anomalies(retention INTERVAL DEFAULT '30 days')
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM anomalies 
    WHERE detected_at < NOW() - retention;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================ 
-- Geofence Helper
-- ============================================ 

CREATE OR REPLACE FUNCTION get_nearby_airport(lat DOUBLE PRECISION, lon DOUBLE PRECISION)
RETURNS TABLE(airport_code VARCHAR(4), airport_name VARCHAR(100), distance_m DOUBLE PRECISION) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        a.code,
        a.name,
        ST_Distance(a.geom, ST_MakePoint(lon, lat)::geography) as dist
    FROM airports a
    WHERE ST_DWithin(a.geom, ST_MakePoint(lon, lat)::geography, 10000)  -- 10km
    ORDER BY dist
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;
