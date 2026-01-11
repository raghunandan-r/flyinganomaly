# Phase 2: Historical Tracking, Anomaly Detection & Time Travel (Final Implementation Guide)

**Objective:** Persist flight data, detect anomalies with context-aware intelligence, visualize flight trails, and enable historical playback.

**Prerequisites:** Phase 1 must be fully operational.

**Canonical Reference:** `docs/final_architecture.md`

---

## 1. Phase 2 Scope

### 1.1 In Scope
- ✅ PostgreSQL/PostGIS database for persistence
- ✅ Historical flight position tracking (24h retention)
- ✅ Bytewax stream processing pipeline
- ✅ Kalman filtering for data quality
- ✅ Airport geofencing for context-aware detection
- ✅ Anomaly detection (Emergency Descent, Go-Around, Holding, Low Altitude Warning)
- ✅ Flight path trail visualization
- ✅ Anomaly highlighting on globe (pulsing rings)
- ✅ Real-time anomaly alerts via WebSocket
- ✅ Time Travel: Historical playback with timeline scrubber
- ✅ Flight details panel

### 1.2 Out of Scope (Future Phases)
- ❌ Wildfire overlay (Phase 3)
- ❌ ML-based anomaly detection (Phase 4)
- ❌ Multi-region support (Phase 4)
- ❌ User authentication (Phase 4)

---

## 2. System Architecture (Phase 2)

```
┌─────────────────────┐
│     OpenSky API     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   Flight Producer   │ (unchanged from Phase 1)
└──────────┬──────────┘
           │
    ┌──────┴──────┐
    ▼             ▼
┌────────┐   ┌────────────┐
│flights │   │  flights   │
│.state  │   │  .updates  │
│(compct)│   │(append-only)│
└───┬────┘   └─────┬──────┘
    │              │
    │              ▼
    │      ┌─────────────────┐
    │      │     Bytewax     │
    │      │ Stream Processor│
    │      │ - Validation    │
    │      │ - Kalman Filter │
    │      │ - Geofence      │
    │      │ - Anomaly Detect│
    │      └────────┬────────┘
    │               │
    │    ┌──────────┼──────────┐
    │    ▼          ▼          ▼
    │ ┌──────┐ ┌────────┐ ┌─────────┐
    │ │Postgr│ │flights │ │anomalies│
    │ │ SQL  │ │.anomaly│ │  table  │
    │ │tables│ │(Kafka) │ │         │
    │ └──┬───┘ └───┬────┘ └─────────┘
    │    │         │
    ▼    ▼         ▼
┌─────────────────────────────┐
│       FastAPI Backend       │
│ - Consumes flights.state    │
│ - Consumes flights.anomalies│
│ - Queries DB for history    │
│ - WS: live + anomalies      │
│ - REST: /history, /anomalies│
└──────────────┬──────────────┘
               │ WebSocket
               ▼
┌─────────────────────────────┐
│      React Frontend         │
│ - Live flights (Phase 1)    │
│ - Flight trails             │
│ - Anomaly highlights        │
│ - Time travel playback      │
│ - Flight details panel      │
└─────────────────────────────┘
```

---

## 3. Database Specification

### 3.1 Docker Compose Addition

Add to `docker-compose.yml`:

```yaml
  postgres:
    image: postgis/postgis:16-3.4
    container_name: postgres
    environment:
      POSTGRES_DB: skysentinel
      POSTGRES_USER: skysentinel
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-skysentinel}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./database/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U skysentinel"]
      interval: 10s
      timeout: 5s
      retries: 5

  processing:
    build:
      context: ./processing
      dockerfile: Dockerfile
    container_name: bytewax_processor
    env_file: .env
    volumes:
      - ./static:/app/static:ro
    depends_on:
      redpanda:
        condition: service_healthy
      postgres:
        condition: service_healthy
    restart: unless-stopped

volumes:
  postgres_data:
```

### 3.2 Database Schema

**File:** `database/init.sql`

```sql
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
```

### 3.3 Data Retention Policy

| Table | Retention | Cleanup Frequency | Method |
|-------|-----------|-------------------|--------|
| `flights_current` | 2 minutes (stale) | Every 30s | Background task in processor |
| `flights_history` | 24 hours | Hourly | pg_cron or app scheduler |
| `anomalies` | 30 days | Daily | pg_cron or app scheduler |

---

## 4. Bytewax Stream Processing

### 4.1 Directory Structure

```
processing/
├── Dockerfile
├── requirements.txt
├── run.py                  # Entry point
├── pipeline.py             # Bytewax dataflow
├── smoothing.py            # Kalman filter
├── geofence.py             # Airport proximity
├── anomaly_detector.py     # Detection rules
├── db_writer.py            # PostgreSQL sink
└── kafka_publisher.py      # Anomaly event publishing
```

### 4.2 `requirements.txt`

```
bytewax>=0.19.0
confluent-kafka>=2.3.0
psycopg[binary]>=3.1.0
shapely>=2.0.0
prometheus-client>=0.19.0
python-dotenv>=1.0.0
```

### 4.3 `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy code
COPY . .

# Run Bytewax
CMD ["python", "-m", "bytewax.run", "pipeline:flow"]
```

### 4.4 `smoothing.py` (Kalman Filter)

```python
"""
Kalman filtering for noisy ADS-B data.

Smooths altitude and vertical rate to reduce false anomaly triggers.
"""

from dataclasses import dataclass, field
from typing import Optional

@dataclass
class KalmanFilter:
    """1D Kalman filter for a single measurement dimension."""
    
    value: float
    estimate_error: float = 10.0
    process_noise: float = 0.1
    measurement_noise: float = 10.0
    
    def update(self, measurement: float) -> float:
        """Process measurement, return smoothed value."""
        # Prediction (assume constant)
        predicted_error = self.estimate_error + self.process_noise
        
        # Update
        kalman_gain = predicted_error / (predicted_error + self.measurement_noise)
        self.value = self.value + kalman_gain * (measurement - self.value)
        self.estimate_error = (1 - kalman_gain) * predicted_error
        
        return self.value
    
    def reset(self, value: float):
        """Reset filter state."""
        self.value = value
        self.estimate_error = self.measurement_noise


@dataclass
class FlightSmoother:
    """Per-flight smoothing state."""
    
    icao24: str
    altitude_filter: Optional[KalmanFilter] = None
    vrate_filter: Optional[KalmanFilter] = None
    last_contact: Optional[int] = None
    
    def process(self, flight: dict) -> dict:
        """Apply smoothing. Adds *_smoothed fields."""
        contact = flight.get("last_contact_unix", 0)
        
        # Reset filters on large time gap (>2 min = likely different flight or data gap)
        if self.last_contact and contact - self.last_contact > 120:
            self.altitude_filter = None
            self.vrate_filter = None
        self.last_contact = contact
        
        # Smooth altitude
        altitude = flight.get("altitude_m")
        if altitude is not None:
            if self.altitude_filter is None:
                self.altitude_filter = KalmanFilter(
                    value=altitude,
                    process_noise=1.0,
                    measurement_noise=30.0  # ~100ft noise
                )
            flight["altitude_m_smoothed"] = self.altitude_filter.update(altitude)
        
        # Smooth vertical rate
        vrate = flight.get("vertical_rate_mps")
        if vrate is not None:
            if self.vrate_filter is None:
                self.vrate_filter = KalmanFilter(
                    value=vrate,
                    process_noise=0.5,
                    measurement_noise=2.0
                )
            flight["vertical_rate_mps_smoothed"] = self.vrate_filter.update(vrate)
        
        return flight
```

### 4.5 `geofence.py` (Airport Context)

```python
"""
Airport geofencing for context-aware anomaly detection.
"""

import json
import os
from shapely.geometry import Point, shape
from shapely.strtree import STRtree
from typing import Optional, Tuple

AIRPORTS_FILE = os.getenv("AIRPORTS_FILE", "static/airports.geojson")
AIRPORT_BUFFER_KM = float(os.getenv("AIRPORT_BUFFER_KM", "10.0"))


class AirportGeofence:
    """Fast airport proximity lookup using spatial index."""
    
    def __init__(self, geojson_path: str = AIRPORTS_FILE, buffer_km: float = AIRPORT_BUFFER_KM):
        self.airports = []
        geometries = []
        
        with open(geojson_path) as f:
            data = json.load(f)
        
        for feature in data["features"]:
            geom = shape(feature["geometry"])
            
            # Buffer point airports
            if geom.geom_type == "Point":
                # ~0.009 degrees per km at NYC latitude
                geom = geom.buffer(buffer_km * 0.009)
            
            self.airports.append({
                "code": feature["properties"]["code"],
                "name": feature["properties"]["name"],
                "type": feature["properties"].get("type", "major"),
                "geometry": geom
            })
            geometries.append(geom)
        
        self.tree = STRtree(geometries)
    
    def get_nearby_airport(self, lat: float, lon: float) -> Tuple[bool, Optional[str]]:
        """Check if point is near any airport. Returns (is_near, airport_code)."""
        point = Point(lon, lat)
        
        for i in self.tree.query(point):
            if self.airports[i]["geometry"].contains(point):
                return True, self.airports[i]["code"]
        
        return False, None
    
    def get_flight_phase(
        self, 
        lat: float, 
        lon: float, 
        altitude_m: Optional[float],
        vertical_rate_mps: Optional[float],
        on_ground: bool
    ) -> str:
        """Determine flight phase based on position and state."""
        if on_ground:
            return "GROUND"
        
        if altitude_m is None:
            return "UNKNOWN"
        
        near_airport, _ = self.get_nearby_airport(lat, lon)
        vrate = vertical_rate_mps or 0
        
        if near_airport:
            if altitude_m < 300:  # ~1000ft
                return "LANDING" if vrate < -1 else "TAKEOFF" if vrate > 1 else "GROUND"
            elif altitude_m < 1000:  # ~3000ft
                return "APPROACH" if vrate < 0 else "DEPARTURE"
            elif altitude_m < 3000:  # ~10000ft
                return "APPROACH" if vrate < -2 else "DEPARTURE" if vrate > 2 else "EN_ROUTE"
        
        return "EN_ROUTE"


# Singleton instance
_geofence: Optional[AirportGeofence] = None

def get_geofence() -> AirportGeofence:
    global _geofence
    if _geofence is None:
        _geofence = AirportGeofence()
    return _geofence
```

### 4.6 `anomaly_detector.py` (Detection Rules)

```python
"""
Anomaly detection rules.

Stateful detectors that maintain per-flight history.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from enum import Enum

from geofence import get_geofence


class AnomalyType(str, Enum):
    EMERGENCY_DESCENT = "EMERGENCY_DESCENT"
    GO_AROUND = "GO_AROUND"
    HOLDING = "HOLDING"
    LOW_ALTITUDE_WARNING = "LOW_ALTITUDE_WARNING"
    SQUAWK_EMERGENCY = "SQUAWK_EMERGENCY"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class Anomaly:
    icao24: str
    callsign: Optional[str]
    anomaly_type: AnomalyType
    severity: Severity
    position: dict
    altitude_m: Optional[float]
    near_airport: Optional[str]
    details: dict
    detected_at: datetime


@dataclass
class FlightState:
    """Per-flight state for anomaly detection."""
    icao24: str
    
    # History buffers
    altitude_history: List[Tuple[datetime, float]] = field(default_factory=list)
    position_history: List[Tuple[datetime, float, float]] = field(default_factory=list)
    vrate_history: List[Tuple[datetime, float]] = field(default_factory=list)
    
    # State machine for Go-Around detection
    approach_started: Optional[datetime] = None
    approach_altitude: Optional[float] = None
    
    # Holding detection
    holding_start: Optional[datetime] = None
    
    MAX_HISTORY = 30  # 5 minutes at 10s intervals


class AnomalyDetector:
    """Stateful anomaly detector for a single flight."""
    
    # Thresholds
    EMERGENCY_DESCENT_THRESHOLD_MPS = 15.24  # 3000 ft/min
    GO_AROUND_CLIMB_THRESHOLD_MPS = 7.62     # 1500 ft/min
    HOLDING_VELOCITY_THRESHOLD_MPS = 100.0
    HOLDING_ALTITUDE_THRESHOLD_M = 3000.0
    HOLDING_POSITION_THRESHOLD_M = 10000.0
    HOLDING_DURATION = timedelta(minutes=5)
    LOW_ALTITUDE_THRESHOLD_M = 300.0  # ~1000ft
    
    def __init__(self):
        self.state: Optional[FlightState] = None
        self.geofence = get_geofence()
    
    def process(self, flight: dict) -> Tuple[dict, List[Anomaly]]:
        """
        Process flight update, detect anomalies. 
        
        Returns:
            (enriched_flight, list_of_anomalies)
        """
        icao24 = flight["icao24"]
        anomalies = []
        
        # Initialize state
        if self.state is None or self.state.icao24 != icao24:
            self.state = FlightState(icao24=icao24)
        
        now = datetime.utcnow()
        pos = flight.get("position", {})
        lat, lon = pos.get("lat"), pos.get("lon")
        
        # Use smoothed values if available
        altitude = flight.get("altitude_m_smoothed") or flight.get("altitude_m")
        vrate = flight.get("vertical_rate_mps_smoothed") or flight.get("vertical_rate_mps")
        
        # Update history
        if altitude is not None:
            self.state.altitude_history.append((now, altitude))
            self.state.altitude_history = self.state.altitude_history[-FlightState.MAX_HISTORY:]
        
        if vrate is not None:
            self.state.vrate_history.append((now, vrate))
            self.state.vrate_history = self.state.vrate_history[-FlightState.MAX_HISTORY:]
        
        if lat is not None and lon is not None:
            self.state.position_history.append((now, lat, lon))
            self.state.position_history = self.state.position_history[-FlightState.MAX_HISTORY:]
        
        # Get airport context
        near_airport, airport_code = self.geofence.get_nearby_airport(lat, lon) if lat and lon else (False, None)
        flight["near_airport"] = airport_code
        flight["flight_phase"] = self.geofence.get_flight_phase(
            lat, lon, altitude, vrate, flight.get("on_ground", False)
        ) if lat and lon else "UNKNOWN"
        
        # Check for squawk emergency codes
        squawk = flight.get("squawk")
        if squawk in ("7700", "7600", "7500"):
            anomalies.append(self._create_anomaly(
                flight, AnomalyType.SQUAWK_EMERGENCY, Severity.HIGH,
                {"squawk": squawk, "meaning": {
                    "7700": "General Emergency",
                    "7600": "Radio Failure", 
                    "7500": "Hijack"
                }.get(squawk)}
            ))
        
        # Rule 1: Emergency Descent
        descent_anomaly = self._check_emergency_descent(flight, vrate, near_airport)
        if descent_anomaly:
            anomalies.append(descent_anomaly)
            flight["status"] = AnomalyType.EMERGENCY_DESCENT.value
        
        # Rule 2: Go-Around
        go_around_anomaly = self._check_go_around(flight, altitude, vrate, near_airport)
        if go_around_anomaly:
            anomalies.append(go_around_anomaly)
            flight["status"] = AnomalyType.GO_AROUND.value
        
        # Rule 3: Low Altitude Warning (away from airports)
        low_alt_anomaly = self._check_low_altitude(flight, altitude, near_airport)
        if low_alt_anomaly:
            anomalies.append(low_alt_anomaly)
            flight["status"] = AnomalyType.LOW_ALTITUDE_WARNING.value
        
        # Rule 4: Holding Pattern
        holding_anomaly = self._check_holding(flight, altitude, vrate)
        if holding_anomaly:
            anomalies.append(holding_anomaly)
            flight["status"] = AnomalyType.HOLDING.value
        
        # Default status
        if "status" not in flight:
            flight["status"] = "NORMAL"
        
        return flight, anomalies
    
    def _check_emergency_descent(
        self, flight: dict, vrate: Optional[float], near_airport: bool
    ) -> Optional[Anomaly]:
        """Detect rapid descent (>3000 ft/min)."""
        if vrate is None or vrate >= -self.EMERGENCY_DESCENT_THRESHOLD_MPS:
            return None
        
        # Ignore if near airport (could be normal landing)
        if near_airport and flight.get("altitude_m", 10000) < 3000:
            return None
        
        # Confirm with history (3 consecutive descending readings)
        if len(self.state.vrate_history) < 3:
            return None
        
        recent = [v for _, v in self.state.vrate_history[-3:]]
        if not all(v < -self.EMERGENCY_DESCENT_THRESHOLD_MPS * 0.8 for v in recent):
            return None
        
        return self._create_anomaly(
            flight, AnomalyType.EMERGENCY_DESCENT, Severity.HIGH,
            {
                "descent_rate_mps": vrate,
                "descent_rate_fpm": vrate * 196.85,
                "confirmed_samples": 3
            }
        )
    
    def _check_go_around(
        self, flight: dict, altitude: Optional[float], vrate: Optional[float], near_airport: bool
    ) -> Optional[Anomaly]:
        """
        Detect go-around: approach abort near airport.
        
        Pattern:
        1. State A: Altitude < 600m (2000ft), near airport, descending
        2. State B: Sudden climb > 1500 ft/min
        3. Transition A→B within 30 seconds
        """
        if altitude is None or vrate is None:
            return None
        
        now = datetime.utcnow()
        
        # Check for approach state
        if near_airport and altitude < 600 and vrate < -2:
            if self.state.approach_started is None:
                self.state.approach_started = now
                self.state.approach_altitude = altitude
        
        # Check for abort (sudden climb while in approach state)
        if self.state.approach_started:
            time_in_approach = now - self.state.approach_started
            
            if vrate > self.GO_AROUND_CLIMB_THRESHOLD_MPS and time_in_approach < timedelta(seconds=60):
                # Detected go-around!
                anomaly = self._create_anomaly(
                    flight, AnomalyType.GO_AROUND, Severity.MEDIUM,
                    {
                        "approach_duration_s": time_in_approach.total_seconds(),
                        "lowest_altitude_m": self.state.approach_altitude,
                        "climb_rate_mps": vrate,
                        "climb_rate_fpm": vrate * 196.85
                    }
                )
                
                # Reset state
                self.state.approach_started = None
                self.state.approach_altitude = None
                
                return anomaly
            
            # Approach timed out or landed
            if time_in_approach > timedelta(seconds=120) or flight.get("on_ground"):
                self.state.approach_started = None
                self.state.approach_altitude = None
        
        return None
    
    def _check_low_altitude(
        self, flight: dict, altitude: Optional[float], near_airport: bool
    ) -> Optional[Anomaly]:
        """Detect dangerously low altitude away from airports."""
        if altitude is None or near_airport or flight.get("on_ground"):
            return None
        
        if altitude < self.LOW_ALTITUDE_THRESHOLD_M:
            return self._create_anomaly(
                flight, AnomalyType.LOW_ALTITUDE_WARNING, Severity.HIGH,
                {
                    "altitude_m": altitude,
                    "altitude_ft": altitude * 3.28084,
                    "threshold_ft": self.LOW_ALTITUDE_THRESHOLD_M * 3.28084
                }
            )
        
        return None
    
    def _check_holding(
        self, flight: dict, altitude: Optional[float], vrate: Optional[float]
    ) -> Optional[Anomaly]:
        """Detect holding pattern (slow, high altitude, same area)."""
        velocity = flight.get("velocity_mps")
        
        if altitude is None or velocity is None:
            return None
        
        # Must be high and slow
        if altitude < self.HOLDING_ALTITUDE_THRESHOLD_M or velocity > self.HOLDING_VELOCITY_THRESHOLD_MPS:
            self.state.holding_start = None
            return None
        
        if len(self.state.position_history) < 2:
            return None
        
        now = datetime.utcnow()
        oldest_time, oldest_lat, oldest_lon = self.state.position_history[0]
        
        if now - oldest_time < self.HOLDING_DURATION:
            return None
        
        # Check if still in same general area
        pos = flight.get("position", {})
        lat, lon = pos.get("lat"), pos.get("lon")
        
        if lat is None or lon is None:
            return None
        
        distance = self._haversine(oldest_lat, oldest_lon, lat, lon)
        
        if distance < self.HOLDING_POSITION_THRESHOLD_M:
            if self.state.holding_start is None:
                self.state.holding_start = oldest_time
            
            return self._create_anomaly(
                flight, AnomalyType.HOLDING, Severity.LOW,
                {
                    "hold_duration_minutes": (now - self.state.holding_start).total_seconds() / 60,
                    "hold_center_lat": oldest_lat,
                    "hold_center_lon": oldest_lon,
                    "distance_from_start_m": distance
                }
            )
        
        self.state.holding_start = None
        return None
    
    def _create_anomaly(
        self, flight: dict, anomaly_type: AnomalyType, severity: Severity, details: dict
    ) -> Anomaly:
        """Create anomaly record."""
        pos = flight.get("position", {})
        return Anomaly(
            icao24=flight["icao24"],
            callsign=flight.get("callsign"),
            anomaly_type=anomaly_type,
            severity=severity,
            position=pos,
            altitude_m=flight.get("altitude_m"),
            near_airport=flight.get("near_airport"),
            details=details,
            detected_at=datetime.utcnow()
        )
    
    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance in meters between two points."""
        import math
        R = 6371000  # Earth radius in meters
        
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))
```

### 4.7 `pipeline.py` (Bytewax Dataflow)

```python
"""
Bytewax Stream Processing Pipeline

Dataflow:
1. Consume from Redpanda topic 'flights.updates'
2. Deserialize and validate
3. Kalman smoothing (stateful, per-aircraft)
4. Geofence enrichment
5. Anomaly detection (stateful, per-aircraft)
6. Write to PostgreSQL
7. Publish anomaly events to Kafka
"""

import os
import json
import logging
from datetime import datetime, timezone

from bytewax.dataflow import Dataflow
from bytewax.inputs import KafkaInputConfig
from bytewax.outputs import ManualOutputConfig
from bytewax.window import TumblingWindow, SystemClockConfig

from smoothing import FlightSmoother
from anomaly_detector import AnomalyDetector, Anomaly
from db_writer import write_to_db
from kafka_publisher import publish_anomaly

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
REDPANDA_BROKER = os.getenv("REDPANDA_BROKER", "redpanda:9092")
KAFKA_TOPIC_UPDATES = os.getenv("KAFKA_TOPIC_UPDATES", "flights.updates")


def deserialize(msg: bytes) -> dict:
    """Deserialize Kafka message."""
    try:
        envelope = json.loads(msg.decode())
        return envelope.get("payload", {})
    except json.JSONDecodeError:
        return {}


class ProcessingState:
    """Combined state for smoothing + anomaly detection."""
    
    def __init__(self):
        self.smoother = None
        self.detector = None
    
    def process(self, flight: dict) -> tuple:
        icao24 = flight.get("icao24")
        if not icao24:
            return flight, []
        
        # Initialize on first use
        if self.smoother is None:
            self.smoother = FlightSmoother(icao24)
        if self.detector is None:
            self.detector = AnomalyDetector()
        
        # Smooth
        flight = self.smoother.process(flight)
        
        # Detect anomalies
        flight, anomalies = self.detector.process(flight)
        
        return flight, anomalies


def output_handler(worker_index: int, worker_count: int):
    """Output handler that writes to DB and publishes anomalies."""
    
    def handler(item):
        icao24, (flight, anomalies) = item
        
        # Write to database
        write_to_db(flight, anomalies)
        
        # Publish anomaly events
        for anomaly in anomalies:
            publish_anomaly(anomaly)
    
    return handler


# Build dataflow
flow = Dataflow()

# Input: Kafka
flow.input(
    "kafka_in",
    KafkaInputConfig(
        brokers=[REDPANDA_BROKER],
        topic=KAFKA_TOPIC_UPDATES,
        starting_offset="end"
    )
)

# Deserialize
flow.map(lambda msg: (msg[0].decode(), deserialize(msg[1])))

# Filter invalid
flow.filter(lambda kv: kv[1].get("icao24") is not None)

# Stateful processing (smoothing + anomaly detection)
flow.stateful_map(
    "process",
    lambda: ProcessingState(),
    lambda state, kv: (kv[0], state.process(kv[1]))
)

# Output: DB + Kafka
flow.output("output", ManualOutputConfig(output_handler))
```

---

## 5. Backend Changes (Phase 2)

### 5.1 New Dependencies

Add to `backend/requirements.txt`:
```
asyncpg>=0.29.0
synchronized[asyncio]>=2.0.25
```

### 5.2 New Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/flights/{icao24}/history` | Position history for trail visualization |
| GET | `/flights/history` | Bulk history for time travel playback |
| GET | `/anomalies` | Active anomalies |
| GET | `/anomalies/{icao24}` | Anomalies for specific flight |

### 5.3 History Endpoint

```python
# backend/routes/history.py

from fastapi import APIRouter, Query
from datetime import datetime, timedelta
import asyncpg

router = APIRouter()

@router.get("/flights/{icao24}/history")
async def get_flight_history(
    icao24: str,
    minutes: int = Query(default=10, ge=1, le=60),
    limit: int = Query(default=100, ge=1, le=1000)
):
    """Get position history for a single flight."""
    since = datetime.utcnow() - timedelta(minutes=minutes)
    
    query = """
        SELECT 
            ST_Y(position::geometry) as lat,
            ST_X(position::geometry) as lon,
            altitude_m,
            heading_deg,
            recorded_at
        FROM flights_history
        WHERE icao24 = $1 AND recorded_at > $2
        ORDER BY recorded_at DESC
        LIMIT $3
    """
    
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(query, icao24, since, limit)
    
    return {
        "icao24": icao24,
        "positions": [
            {
                "position": {"lat": r["lat"], "lon": r["lon"]},
                "altitude_m": r["altitude_m"],
                "heading_deg": r["heading_deg"],
                "recorded_at": r["recorded_at"].isoformat()
            }
            for r in reversed(rows)
        ]
    }


@router.get("/flights/history")
async def get_bulk_history(
    start_ts: datetime,
    end_ts: datetime,
    interval_s: int = Query(default=10, ge=5, le=60)
):
    """
    Get history for all flights in time range.
    Used for time travel playback.
    """
    query = """
        WITH sampled AS (
            SELECT 
                icao24,
                callsign,
                ST_Y(position::geometry) as lat,
                ST_X(position::geometry) as lon,
                altitude_m,
                heading_deg,
                velocity_mps,
                on_ground,
                recorded_at,
                ROW_NUMBER() OVER (
                    PARTITION BY icao24, 
                    date_trunc('second', recorded_at) - 
                    (EXTRACT(EPOCH FROM recorded_at)::int % $3 * interval '1 second')
                    ORDER BY recorded_at
                ) as rn
            FROM flights_history
            WHERE recorded_at BETWEEN $1 AND $2
        )
        SELECT * FROM sampled WHERE rn = 1
        ORDER BY recorded_at
    """
    
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(query, start_ts, end_ts, interval_s)
    
    # Group by timestamp
    frames = {}
    for r in rows:
        ts = r["recorded_at"].isoformat()
        if ts not in frames:
            frames[ts] = []
        frames[ts].append({
            "icao24": r["icao24"],
            "callsign": r["callsign"],
            "position": {"lat": r["lat"], "lon": r["lon"]},
            "altitude_m": r["altitude_m"],
            "heading_deg": r["heading_deg"],
            "velocity_mps": r["velocity_mps"],
            "on_ground": r["on_ground"]
        })
    
    return {
        "start": start_ts.isoformat(),
        "end": end_ts.isoformat(),
        "frames": [
            {"timestamp": ts, "flights": flights}
            for ts, flights in sorted(frames.items())
        ]
    }
```

### 5.4 WebSocket: Anomaly Stream

Modify backend to also consume `flights.anomalies` and multiplex to WebSocket:

```python
# backend/anomaly_consumer.py

async def anomaly_consumer_task(manager: ConnectionManager):
    """Consume anomaly events and broadcast to WebSocket clients."""
    
    config = {
        "bootstrap.servers": REDPANDA_BROKER,
        "group.id": "skysentinel-backend-anomalies",
        "auto.offset.reset": "latest"
    }
    
    consumer = Consumer(config)
    consumer.subscribe(["flights.anomalies"])
    
    while True:
        msg = consumer.poll(timeout=0.1)
        
        if msg is None:
            await asyncio.sleep(0.01)
            continue
        
        if msg.error():
            continue
        
        try:
            envelope = json.loads(msg.value().decode())
            
            # Broadcast anomaly to all clients
            ws_message = {
                "type": "anomaly",
                "timestamp": datetime.utcnow().isoformat(),
                "payload": envelope.get("payload", {})
            }
            
            await manager.broadcast(ws_message)
            
        except json.JSONDecodeError:
            pass
```

---

## 6. Frontend Changes (Phase 2)

### 6.1 New Components

| Component | Purpose |
|-----------|---------|
| `FlightTrail.tsx` | Render historical path on globe |
| `AnomalyHighlight.tsx` | Pulsing ring for anomaly aircraft |
| `FlightDetailsPanel.tsx` | Slide-out panel with flight info |
| `AnomalyList.tsx` | List of active anomalies |
| `TimeTravel.tsx` | Timeline scrubber for playback |

### 6.2 Flight Trails

```tsx
// components/FlightTrail.tsx

import { useEffect, useState } from 'react';
import { Flight } from '../types/flight';

interface TrailData {
  icao24: string;
  positions: Array<{ lat: number; lon: number }>;
  status: string;
}

export function useFlightTrails(
  selectedFlight: string | null,
  apiUrl: string
): TrailData | null {
  const [trail, setTrail] = useState<TrailData | null>(null);
  
  useEffect(() => {
    if (!selectedFlight) {
      setTrail(null);
      return;
    }
    
    const fetchTrail = async () => {
      const res = await fetch(`${apiUrl}/flights/${selectedFlight}/history?minutes=10`);
      const data = await res.json();
      
      setTrail({
        icao24: data.icao24,
        positions: data.positions.map((p: any) => ({
          lat: p.position.lat,
          lon: p.position.lon
        })),
        status: 'NORMAL'
      });
    };
    
    fetchTrail();
    const interval = setInterval(fetchTrail, 10000);
    
    return () => clearInterval(interval);
  }, [selectedFlight, apiUrl]);
  
  return trail;
}

// In FlightGlobe.tsx, add:
globe.pathsData(trail ? [trail] : [])
  .pathPoints(d => d.positions)
  .pathPointLat(p => p.lat)
  .pathPointLng(p => p.lon)
  .pathColor(d => d.status === 'NORMAL' ? 'rgba(0, 255, 0, 0.5)' : 'rgba(255, 0, 0, 0.7)')
  .pathStroke(2)
  .pathDashLength(0.5)
  .pathDashGap(0.1)
  .pathDashAnimateTime(2000);
```

### 6.3 Time Travel Playback

```tsx
// components/TimeTravel.tsx

import { useState, useEffect, useCallback } from 'react';
import { Flight } from '../types/flight';

interface TimeTravelProps {
  apiUrl: string;
  onFrame: (flights: Flight[]) => void;
  onModeChange: (isPlayback: boolean) => void;
}

export function TimeTravel({ apiUrl, onFrame, onModeChange }: TimeTravelProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [frames, setFrames] = useState<Array<{ timestamp: string; flights: Flight[] }>>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  
  // Load history
  const loadHistory = useCallback(async (minutes: number) => {
    const end = new Date();
    const start = new Date(end.getTime() - minutes * 60 * 1000);
    
    const res = await fetch(
      `${apiUrl}/flights/history?start_ts=${start.toISOString()}&end_ts=${end.toISOString()}`
    );
    const data = await res.json();
    
    setFrames(data.frames);
    setCurrentIndex(0);
    onModeChange(true);
  }, [apiUrl, onModeChange]);
  
  // Playback loop
  useEffect(() => {
    if (!isPlaying || frames.length === 0) return;
    
    const interval = setInterval(() => {
      setCurrentIndex(prev => {
        const next = prev + 1;
        if (next >= frames.length) {
          setIsPlaying(false);
          return prev;
        }
        onFrame(frames[next].flights);
        return next;
      });
    }, 1000 / playbackSpeed);
    
    return () => clearInterval(interval);
  }, [isPlaying, frames, playbackSpeed, onFrame]);
  
  // Seek
  const seek = (index: number) => {
    setCurrentIndex(index);
    if (frames[index]) {
      onFrame(frames[index].flights);
    }
  };
  
  return (
    <div className="time-travel">
      <div className="controls">
        <button onClick={() => loadHistory(30)}>Load 30 min</button>
        <button onClick={() => loadHistory(60)}>Load 1 hr</button>
        <button onClick={() => { onModeChange(false); setFrames([]); }}>
          Live
        </button>
      </div>
      
      {frames.length > 0 && (
        <>
          <div className="playback">
            <button onClick={() => setIsPlaying(!isPlaying)}>
              {isPlaying ? '⏸' : '▶'}
            </button>
            <select 
              value={playbackSpeed} 
              onChange={e => setPlaybackSpeed(+e.target.value)}
            >
              <option value={1}>1x</option>
              <option value={5}>5x</option>
              <option value={10}>10x</option>
            </select>
          </div>
          
          <input
            type="range"
            min={0}
            max={frames.length - 1}
            value={currentIndex}
            onChange={e => seek(+e.target.value)}
            className="timeline"
          />
          
          <div className="timestamp">
            {frames[currentIndex]?.timestamp}
          </div>
        </>
      )}
    </div>
  );
}
```

### 6.4 Anomaly Visualization

```tsx
// In FlightGlobe.tsx, add anomaly rings:

const highSeverityAnomalies = anomalies.filter(a => a.severity === 'HIGH');

globe.ringsData(highSeverityAnomalies)
  .ringLat(a => a.position.lat)
  .ringLng(a => a.position.lon)
  .ringColor(() => '#ff0000')
  .ringMaxRadius(3)
  .ringPropagationSpeed(2)
  .ringRepeatPeriod(1000);
```

---

## 7. Testing Checklist (Phase 2)

### 7.1 Unit Tests
- [ ] Kalman filter convergence
- [ ] Geofence accuracy (point-in-polygon)
- [ ] Anomaly detection rules (emergency descent, go-around, holding)
- [ ] DB write correctness

### 7.2 Integration Tests
- [ ] Bytewax pipeline end-to-end
- [ ] History API returns correct data
- [ ] Anomaly events published to Kafka
- [ ] WebSocket receives anomaly messages

### 7.3 Manual Testing
- [ ] Flight trails render correctly
- [ ] Anomaly rings pulse on HIGH severity
- [ ] Time travel scrubber works
- [ ] Go-around detection triggers on simulated data

---

## 8. Deployment Checklist (Phase 2)

```bash
# 1. Update docker-compose to include Phase 2 services
docker compose --profile phase2 up -d

# 2. Verify database
docker exec postgres psql -U skysentinel -d skysentinel -c "\dt"

# 3. Verify Bytewax is processing
docker logs -f bytewax_processor

# 4. Verify history is being written
docker exec postgres psql -U skysentinel -d skysentinel -c \
  "SELECT COUNT(*) FROM flights_history WHERE recorded_at > NOW() - interval '5 minutes'"

# 5. Test history API
curl "http://localhost:8000/flights/a0b1c2/history?minutes=5" | jq

# 6. Test anomalies API
curl "http://localhost:8000/anomalies" | jq

# 7. Open frontend and verify trails + time travel
```

---

## 9. Summary: Documents for Implementation

| Document | Purpose | Status |
|----------|---------|--------|
| `final_architecture.md` | Canonical architecture (schemas, topics, services) | ✅ Complete |
| `final_phase1.md` | Phase 1 implementation guide | ✅ Complete |
| `final_phase2.md` | Phase 2 implementation guide | ✅ Complete |

**Legacy documents (reference only):**
- `description.md`, `plan.md` - Original high-level docs
- `architecture_v2.md`, `phase1_flights.md`, `phase2_history.md` - Previous iterations
- `gemini_*.md` - Competing proposals (now integrated)

```