# SkySentinel Architecture (Final Canonical Specification)

**Version:** 4.0 (Ultimate Hybrid)

This document is the **single source of truth** for:
- Event contracts (schemas, invariants, units)
- Topic layout (what each stream means, retention, compaction)
- Service responsibilities (who publishes/consumes what)
- Data quality pipeline (smoothing, validation, enrichment)
- Observability specification (metrics, dashboards, alerting)
- Scaling assumptions and upgrade paths

Referenced by:
- `docs/final_phase1.md` (live visualization MVP)
- `docs/final_phase2.md` (history + anomaly detection + time travel)

---

## 1. Core Design Principles

### 1.1 Data Architecture
1. **Separate "latest state" from "event log"**
   - Use a **compacted** topic for the latest per-aircraft state (UI bootstrap).
   - Use an **append-only** topic for time-ordered observations (history + anomaly detection).

2. **One real-time source of truth for the UI**
   - The UI subscribes to a single stream for live aircraft (`flights.state`), not to a database trigger.
   - Kafka/Redpanda is the realtime spine; Postgres is for queries/history, not push.

3. **No client-driven fan-out from Kafka**
   - Kafka consumers run **inside the backend**, not one per WebSocket client.
   - The backend is a "realtime hub" that multiplexes to many WS clients.

### 1.2 Data Quality
4. **Smooth before analysis**
   - Apply Kalman filtering to noisy ADS-B altitude/velocity before anomaly detection.
   - Reduces false positives from sensor jitter.

5. **Context-aware intelligence**
   - Raw flight data is insufficient; we need static context (airport locations, runways) to determine if behavior is anomalous or normal.

### 1.3 Observability
6. **If it moves, measure it**
   - Every component emits Prometheus metrics.
   - Centralized Grafana dashboards for pipeline health.

### 1.4 Developer Experience
7. **Replay mode for deterministic testing**
   - The entire pipeline can run from recorded fixtures without live API access.
   - Enables demos, regression tests, and edge-case reproduction.

8. **Schema versioning is mandatory**
   - Every payload includes `schema_version` so consumers can handle evolution gracefully.

### 1.5 Performance
9. **Binary transport for high-frequency paths**
   - WebSocket supports MessagePack (optional) for ~50% bandwidth reduction.
   - JSON remains default for debuggability.

10. **Delta updates, not full snapshots**
    - After initial snapshot, only send changed flights + removals.

---

## 2. Topics (Redpanda / Kafka)

### 2.1 Topic Summary

| Topic | Type | Key | Retention | Purpose |
|-------|------|-----|-----------|---------|
| `flights.updates` | Append-only | `icao24` | 7d time-delete | Durable log of all observations (Phase 2 source) |
| `flights.state` | Compacted | `icao24` | Compaction | Latest state per aircraft (Phase 1 UI source) |
| `flights.anomalies` | Append-only | `icao24` | 30d time-delete | Anomaly events for realtime alerting |
| `ingestion.heartbeat` | Append-only | `producer_id` | 24h time-delete | Producer health, poll latency, API stats |
| `deadletter.flights` | Append-only | - | 7d time-delete | Invalid payloads for debugging |

### 2.2 Topic Details

#### `flights.updates` (Append-only observation stream)
- **Purpose**: Durable event log of all per-aircraft updates used by Phase 2 processing (Bytewax).
- **Value**: `FlightUpdateEnvelope`
- **Compaction**: Disabled
- **Consumers**: Bytewax pipeline

#### `flights.state` (Compacted latest-state stream)
- **Purpose**: Latest known state per aircraft for Phase 1 UI and quick snapshot queries.
- **Value**: `FlightStateEnvelope`
- **Compaction**: Enabled (log.cleanup.policy=compact)
- **Consumers**: FastAPI backend (realtime hub)

#### `flights.anomalies` (Append-only anomaly events)
- **Purpose**: Anomaly events emitted by Phase 2 processing for realtime UI alerts.
- **Value**: `AnomalyEventEnvelope`
- **Consumers**: FastAPI backend (multiplexed to WebSocket)

---

## 3. Canonical Schemas (JSON)

### 3.1 Envelope Structure (Required for All Topics)

All messages use a versioned envelope for forward compatibility:

```json
{
  "schema_version": 1,
  "type": "flight_state | flight_update | anomaly_event | heartbeat",
  "produced_at": "2026-01-09T12:00:00.000Z",
  "source": {
    "provider": "opensky",
    "mode": "live | replay",
    "bbox": {
      "lat_min": 40.40,
      "lat_max": 41.20,
      "lon_min": -74.50,
      "lon_max": -73.50
    },
    "poll_interval_s": 10
  },
  "payload": { }
}
```

### 3.2 `FlightPayload` (Core Flight Data)

```json
{
  "icao24": "a0b1c2",
  "callsign": "UAL123",
  "position": {
    "lat": 40.6413,
    "lon": -73.7781
  },
  "altitude_m": 3048.0,
  "geo_altitude_m": 3100.0,
  "velocity_mps": 125.5,
  "heading_deg": 270.0,
  "vertical_rate_mps": -5.2,
  "on_ground": false,
  "squawk": "1200",
  "spi": false,
  "time_position_unix": 1704672000,
  "last_contact_unix": 1704672005
}
```

#### Field Reference

| Field | Type | OpenSky Index | Units | Notes |
|-------|------|---------------|-------|-------|
| `icao24` | string | 0 | - | ICAO 24-bit address (hex, lowercase) |
| `callsign` | string/null | 1 | - | Trimmed; may be empty or null |
| `position.lat` | float | 6 | degrees | WGS84, range [-90, 90] |
| `position.lon` | float | 5 | degrees | WGS84, range [-180, 180] |
| `altitude_m` | float/null | 7 | meters | Barometric altitude (prefer for consistency) |
| `geo_altitude_m` | float/null | 13 | meters | Geometric altitude (optional) |
| `velocity_mps` | float/null | 9 | m/s | Ground speed |
| `heading_deg` | float/null | 10 | degrees | True track [0, 360) |
| `vertical_rate_mps` | float/null | 11 | m/s | Positive = climbing |
| `on_ground` | bool | 8 | - | True if on ground |
| `squawk` | string/null | 14 | - | Transponder code (e.g., "7700") |
| `spi` | bool | 15 | - | Special Purpose Indicator |
| `time_position_unix` | int/null | 3 | seconds | Unix timestamp of position |
| `last_contact_unix` | int | 4 | seconds | Most recent message (freshness clock) |

#### Invariants
- `position.lat` in [-90, 90], `position.lon` in [-180, 180]
- `heading_deg` in [0, 360)
- All `*_unix` fields are seconds since epoch (UTC)
- Missing fields from OpenSky may be `null` and must not crash consumers
- Use `last_contact_unix` as the authoritative freshness clock

### 3.3 `AnomalyPayload`

```json
{
  "icao24": "a0b1c2",
  "callsign": "UAL123",
  "anomaly_type": "EMERGENCY_DESCENT",
  "severity": "HIGH",
  "detected_at": "2026-01-09T12:00:15.000Z",
  "position": {
    "lat": 40.65,
    "lon": -73.77
  },
  "details": {
    "descent_rate_mps": -20.3,
    "descent_rate_fpm": -3996,
    "confirmed_samples": 3
  }
}
```

#### Anomaly Types

| Type | Trigger | Severity | Description |
|------|---------|----------|-------------|
| `EMERGENCY_DESCENT` | Descent > 3000 ft/min sustained | HIGH | Potential emergency |
| `GO_AROUND` | Approach abort near airport | MEDIUM | Attempted landing, then climb |
| `HOLDING` | Slow, high altitude, same area >5 min | LOW | Traffic holding pattern |
| `LOW_ALTITUDE_WARNING` | Low altitude away from airports | HIGH | Potential CFIT risk |
| `SQUAWK_7700` | Transponder emergency code | HIGH | Declared emergency |
| `SQUAWK_7600` | Transponder radio failure code | MEDIUM | Radio failure |
| `SQUAWK_7500` | Transponder hijack code | HIGH | Hijack indication |

### 3.4 `HeartbeatPayload`

```json
{
  "producer_id": "producer-1",
  "timestamp": "2026-01-09T12:00:00.000Z",
  "poll_latency_ms": 342,
  "api_status": "ok | rate_limited | error",
  "flights_count": 127,
  "bbox": { "lat_min": 40.40, "lat_max": 41.20, "lon_min": -74.50, "lon_max": -73.50 }
}
```

---

## 4. Reference Data (Static)

### 4.1 Airport Geofencing

**File:** `static/airports.geojson`

Polygons/points for major airports in the bounding box. Used for:
- **Producer/Processor**: Tag `flight_phase` (TAKEOFF, EN_ROUTE, APPROACH, LANDING)
- **Anomaly Detection**: Suppress false positives near airports
- **Frontend**: Visualize airport zones

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "code": "JFK",
        "name": "John F. Kennedy International",
        "type": "major",
        "runway_heading_primary": 310
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[-73.8, 40.62], [-73.75, 40.62], [-73.75, 40.66], [-73.8, 40.66], [-73.8, 40.62]]]
      }
    },
    {
      "type": "Feature",
      "properties": { "code": "LGA", "name": "LaGuardia", "type": "major" },
      "geometry": { "type": "Point", "coordinates": [-73.8740, 40.7769] }
    },
    {
      "type": "Feature",
      "properties": { "code": "EWR", "name": "Newark Liberty International", "type": "major" },
      "geometry": { "type": "Point", "coordinates": [-74.1745, 40.6895] }
    },
    {
      "type": "Feature",
      "properties": { "code": "TEB", "name": "Teterboro", "type": "general_aviation" },
      "geometry": { "type": "Point", "coordinates": [-74.0608, 40.8501] }
    }
  ]
}
```

### 4.2 Geofence Utilities

```python
# utils/geofence.py

from shapely.geometry import Point, shape
from shapely.strtree import STRtree
import json

class AirportGeofence:
    """Fast airport proximity lookup using R-tree spatial index."""
    
    def __init__(self, geojson_path: str, buffer_km: float = 10.0):
        with open(geojson_path) as f:
            data = json.load(f)
        
        self.airports = []
        geometries = []
        
        for feature in data["features"]:
            geom = shape(feature["geometry"])
            # Buffer point airports to create proximity zone
            if geom.geom_type == "Point":
                # Approximate buffer in degrees (~0.009 per km at this latitude)
                geom = geom.buffer(buffer_km * 0.009)
            self.airports.append({
                "code": feature["properties"]["code"],
                "name": feature["properties"]["name"],
                "geometry": geom
            })
            geometries.append(geom)
        
        self.tree = STRtree(geometries)
    
    def is_near_airport(self, lat: float, lon: float) -> tuple[bool, str | None]:
        """Check if point is near any airport. Returns (is_near, airport_code)."""
        point = Point(lon, lat)
        for i in self.tree.query(point):
            if self.airports[i]["geometry"].contains(point):
                return True, self.airports[i]["code"]
        return False, None
    
    def get_flight_phase(self, lat: float, lon: float, altitude_m: float, 
                         vertical_rate_mps: float, on_ground: bool) -> str:
        """Determine flight phase based on position and state."""
        if on_ground:
            return "GROUND"
        
        near_airport, _ = self.is_near_airport(lat, lon)
        
        if near_airport and altitude_m < 1000:
            if vertical_rate_mps < -2:
                return "LANDING"
            elif vertical_rate_mps > 2:
                return "TAKEOFF"
            else:
                return "APPROACH"
        elif near_airport and altitude_m < 3000:
            return "APPROACH" if vertical_rate_mps < 0 else "DEPARTURE"
        else:
            return "EN_ROUTE"
```

---

## 5. Data Quality Pipeline

### 5.1 Kalman Filtering

Raw ADS-B data contains sensor noise (altitude can fluctuate ±100ft between readings). Apply Kalman filtering to smooth inputs before anomaly detection.

```python
# processing/smoothing.py

class SimpleKalman:
    """
    1D Kalman filter for smoothing noisy measurements.
    
    Use per-aircraft, per-dimension (altitude, velocity, etc.).
    """
    
    def __init__(
        self,
        initial_value: float,
        process_noise: float = 0.1,
        measurement_noise: float = 10.0,
        initial_estimate_error: float = 10.0
    ):
        self.value = initial_value
        self.estimate_error = initial_estimate_error
        self.process_noise = process_noise
        self.measurement_noise = measurement_noise
    
    def update(self, measurement: float) -> float:
        """Process new measurement, return smoothed value."""
        # Prediction step (assume constant model)
        predicted_value = self.value
        predicted_error = self.estimate_error + self.process_noise
        
        # Update step
        kalman_gain = predicted_error / (predicted_error + self.measurement_noise)
        self.value = predicted_value + kalman_gain * (measurement - predicted_value)
        self.estimate_error = (1 - kalman_gain) * predicted_error
        
        return self.value
    
    def reset(self, value: float):
        """Reset filter state (e.g., on large discontinuity)."""
        self.value = value
        self.estimate_error = self.measurement_noise


class FlightSmoother:
    """Per-flight Kalman smoothing for altitude and vertical rate."""
    
    def __init__(self):
        self.altitude_filter: SimpleKalman | None = None
        self.vrate_filter: SimpleKalman | None = None
        self.last_contact: int | None = None
    
    def process(self, flight: dict) -> dict:
        """Apply smoothing to flight data. Modifies in place and returns."""
        altitude = flight.get("altitude_m")
        vrate = flight.get("vertical_rate_mps")
        contact = flight.get("last_contact_unix", 0)
        
        # Reset filters if large time gap (aircraft likely different or data gap)
        if self.last_contact and contact - self.last_contact > 120:
            self.altitude_filter = None
            self.vrate_filter = None
        self.last_contact = contact
        
        # Smooth altitude
        if altitude is not None:
            if self.altitude_filter is None:
                self.altitude_filter = SimpleKalman(altitude, process_noise=1.0, measurement_noise=50.0)
            flight["altitude_m_raw"] = altitude
            flight["altitude_m"] = self.altitude_filter.update(altitude)
        
        # Smooth vertical rate
        if vrate is not None:
            if self.vrate_filter is None:
                self.vrate_filter = SimpleKalman(vrate, process_noise=0.5, measurement_noise=2.0)
            flight["vertical_rate_mps_raw"] = vrate
            flight["vertical_rate_mps"] = self.vrate_filter.update(vrate)
        
        return flight
```

### 5.2 Validation Rules

```python
# processing/validation.py

def validate_flight(flight: dict) -> tuple[bool, list[str]]:
    """Validate flight payload. Returns (is_valid, list_of_errors)."""
    errors = []
    
    # Required fields
    if not flight.get("icao24"):
        errors.append("missing icao24")
    
    # Position bounds
    pos = flight.get("position", {})
    lat, lon = pos.get("lat"), pos.get("lon")
    if lat is None or lon is None:
        errors.append("missing position")
    elif not (-90 <= lat <= 90 and -180 <= lon <= 180):
        errors.append(f"invalid position: lat={lat}, lon={lon}")
    
    # Heading bounds
    heading = flight.get("heading_deg")
    if heading is not None and not (0 <= heading < 360):
        errors.append(f"invalid heading: {heading}")
    
    # Altitude sanity (commercial aircraft typically < 45000 ft / 13716 m)
    alt = flight.get("altitude_m")
    if alt is not None and (alt < -500 or alt > 20000):
        errors.append(f"suspicious altitude: {alt}m")
    
    # Velocity sanity (commercial aircraft typically < 300 m/s ground speed)
    vel = flight.get("velocity_mps")
    if vel is not None and (vel < 0 or vel > 400):
        errors.append(f"suspicious velocity: {vel} m/s")
    
    return len(errors) == 0, errors
```

---

## 6. Services (Responsibilities & Interfaces)

### 6.1 `ingestion/producer_flight.py`

**Responsibilities:**
- Poll OpenSky API for configured bbox (or replay from fixture).
- Normalize records into `FlightPayload`.
- Publish to both topics:
  - `FlightUpdateEnvelope` → `flights.updates` (append-only)
  - `FlightStateEnvelope` → `flights.state` (compacted)
- Emit `ingestion.heartbeat` metrics per poll cycle.
- Route invalid payloads to `deadletter.flights`.

**Modes:**
- `OPENSKY_MODE=live`: Poll OpenSky API in real-time.
- `OPENSKY_MODE=replay`: Read from `REPLAY_FILE` and publish with timing preserved (or accelerated via `REPLAY_SPEED`).

### 6.2 `backend/` (FastAPI Realtime Hub)

**Responsibilities:**
- Run **one** Kafka consumer per backend instance for `flights.state`.
- Maintain in-memory cache `icao24 → FlightPayload + last_seen`.
- Handle out-of-order messages (reject if `last_contact_unix` is older than cached).
- WebSocket endpoint:
  - Send `snapshot` on connect.
  - Send `delta` updates at fixed cadence (2-5 Hz) with `upserts` and `removed` lists.
  - Support optional MessagePack encoding via `sec-websocket-protocol: msgpack`.
- Expose REST endpoints for current state (`GET /flights`).
- Expose Prometheus metrics at `/metrics`.
- (Phase 2) Also consume `flights.anomalies` and multiplex to WebSocket.

### 6.3 `processing/` (Bytewax - Phase 2)

**Responsibilities:**
- Consume `flights.updates`.
- Apply Kalman smoothing.
- Enrich with airport geofence context.
- Detect anomalies (stateful, per-aircraft).
- Write to PostgreSQL (history + current + anomalies).
- Publish anomaly events to `flights.anomalies`.

### 6.4 `frontend/` (React + Globe.gl)

**Responsibilities:**
- Connect to WebSocket, handle reconnection with exponential backoff.
- Maintain local flight state from `snapshot` + `delta` messages.
- Render flights on 3D globe with smooth interpolation.
- Support filters (altitude, on-ground, callsign search).
- (Phase 1) Ghost interpolation visualization for data freshness.
- (Phase 1) Cockpit View camera lock.
- (Phase 2) Flight trails, anomaly highlights, time travel playback.

---

## 7. Observability Specification

### 7.1 Prometheus Metrics

#### Producer Metrics
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `producer_polls_total` | Counter | `status` | Total API poll attempts |
| `producer_poll_latency_seconds` | Histogram | - | API poll duration |
| `producer_flights_published_total` | Counter | `topic` | Flights published |
| `producer_api_errors_total` | Counter | `error_type` | API errors by type |
| `producer_deadletter_total` | Counter | - | Invalid payloads sent to DLQ |

#### Backend Metrics
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `backend_kafka_consumer_lag` | Gauge | `topic`, `partition` | Consumer lag |
| `backend_flights_cached` | Gauge | - | Current flights in cache |
| `backend_websocket_connections` | Gauge | - | Active WS connections |
| `backend_websocket_messages_sent_total` | Counter | `type` | Messages by type |
| `backend_http_requests_total` | Counter | `method`, `path`, `status` | HTTP requests |

#### Processing Metrics (Phase 2)
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `processing_messages_processed_total` | Counter | - | Messages processed |
| `processing_anomalies_detected_total` | Counter | `type`, `severity` | Anomalies by type |
| `processing_db_write_latency_seconds` | Histogram | `table` | DB write duration |

### 7.2 Grafana Dashboards

**Dashboard: SkySentinel Overview**

| Panel | Type | Query |
|-------|------|-------|
| Pipeline Health | Stat | `up{job=~"producer|backend|processing"}` |
| Ingestion Rate | Graph | `rate(producer_flights_published_total[1m])` |
| Consumer Lag | Graph | `backend_kafka_consumer_lag` |
| Active Flights | Stat | `backend_flights_cached` |
| WebSocket Clients | Stat | `backend_websocket_connections` |
| API Poll Latency | Graph | `histogram_quantile(0.95, producer_poll_latency_seconds)` |
| Anomalies/Hour | Graph | `increase(processing_anomalies_detected_total[1h])` |
| Error Rate | Graph | `rate(producer_api_errors_total[5m])` |

### 7.3 Alerting Rules

```yaml
# prometheus/alerts.yml
groups:
  - name: skysentinel
    rules:
      - alert: ProducerDown
        expr: up{job="producer"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Flight producer is down"
      
      - alert: HighConsumerLag
        expr: backend_kafka_consumer_lag > 1000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Kafka consumer lag is high"
      
      - alert: NoFlightsIngested
        expr: rate(producer_flights_published_total[5m]) == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "No flights being ingested"
```

---

## 8. WebSocket Protocol Specification

### 8.1 Connection

**Endpoint:** `ws://localhost:8000/ws/flights`

**Subprotocol Negotiation:**
- Client sends `Sec-WebSocket-Protocol: json, msgpack`
- Server responds with chosen protocol
- Default: `json` (human-readable)
- Optional: `msgpack` (binary, ~50% smaller)

### 8.2 Message Types (Server → Client)

#### Snapshot (sent on connect)
```json
{
  "type": "snapshot",
  "timestamp": "2026-01-09T12:00:00.000Z",
  "sequence": 0,
  "flights": [
    {
      "icao24": "a0b1c2",
      "callsign": "UAL123",
      "position": { "lat": 40.6413, "lon": -73.7781 },
      "altitude_m": 3048.0,
      "heading_deg": 270.0,
      "velocity_mps": 125.5,
      "vertical_rate_mps": -2.1,
      "on_ground": false,
      "status": "NORMAL"
    }
  ]
}
```

#### Delta (sent continuously)
```json
{
  "type": "delta",
  "timestamp": "2026-01-09T12:00:10.000Z",
  "sequence": 43,
  "upserts": [
    {
      "icao24": "a0b1c2",
      "callsign": "UAL123",
      "position": { "lat": 40.6500, "lon": -73.7700 },
      "altitude_m": 3100.0,
      "heading_deg": 271.0,
      "velocity_mps": 126.0,
      "vertical_rate_mps": -1.8,
      "on_ground": false,
      "status": "NORMAL"
    }
  ],
  "removed": ["deadbe", "abc123"]
}
```

#### Anomaly (Phase 2)
```json
{
  "type": "anomaly",
  "timestamp": "2026-01-09T12:00:15.000Z",
  "payload": {
    "icao24": "a0b1c2",
    "callsign": "UAL123",
    "anomaly_type": "EMERGENCY_DESCENT",
    "severity": "HIGH",
    "position": { "lat": 40.65, "lon": -73.77 },
    "details": { "descent_rate_fpm": -4000 }
  }
}
```

### 8.3 MessagePack Format (Optional)

When using MessagePack, messages are encoded as compact arrays:

**Delta format:**
```
[
  sequence_id: int,
  timestamp_ms: int,
  upserts: [
    [icao24, lat, lon, alt_m, heading_deg, velocity_mps, vrate_mps, on_ground, status],
    ...
  ],
  removed: [icao24, ...]
]
```

**Benefits:**
- ~50% bandwidth reduction
- Faster parsing on client
- Lower CPU usage

---

## 9. Scaling Model

### 9.1 Phase 1 Assumptions (Acceptable)

- One backend instance, one consumer, many WebSocket clients.
- Expected: 50-200 flights, 10-50 WebSocket clients.
- Delta updates at 2-5 Hz cap bandwidth.

### 9.2 Scaling Triggers

| Symptom | Threshold | Solution |
|---------|-----------|----------|
| Consumer lag growing | >1000 messages | Increase consumer threads or add instance |
| WS broadcast latency | >100ms | Reduce delta frequency or batch larger |
| Memory pressure | >80% | Reduce cache retention or add instance |
| >100 WS clients | - | Add Redis pub/sub or dedicated WS gateway |

### 9.3 Multi-Instance Architecture (Future)

For multiple backend replicas:
1. **Option A**: Shared Redis pub/sub layer between Kafka consumer and WebSocket broadcasters.
2. **Option B**: Dedicated "realtime hub" service that owns Kafka consumers, other backends subscribe.
3. **Option C**: Use a specialized WebSocket gateway (Centrifugo, Soketi) for thousands of connections.

---

## 10. Deployment Stack

### 10.1 Docker Compose (Development)

```yaml
version: '3.8'

services:
  redpanda:
    image: redpandadata/redpanda:v24.1.1
    container_name: redpanda
    command:
      - redpanda start
      - --smp 1
      - --memory 1G
      - --overprovisioned
      - --node-id 0
      - --kafka-addr PLAINTEXT://0.0.0.0:9092
      - --advertise-kafka-addr PLAINTEXT://redpanda:9092
    ports:
      - "9092:9092"
      - "9644:9644"
    healthcheck:
      test: ["CMD", "rpk", "cluster", "health"]
      interval: 10s
      timeout: 5s
      retries: 5

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

  producer:
    build:
      context: ./ingestion
      dockerfile: Dockerfile
    container_name: flight_producer
    env_file: .env
    volumes:
      - ./fixtures:/app/fixtures:ro
      - ./static:/app/static:ro
    depends_on:
      redpanda:
        condition: service_healthy
    restart: unless-stopped

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: backend_api
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      redpanda:
        condition: service_healthy
    restart: unless-stopped

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
    profiles:
      - phase2

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: frontend_app
    ports:
      - "3000:3000"
    depends_on:
      - backend

  prometheus:
    image: prom/prometheus:v2.48.0
    container_name: prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - ./prometheus/alerts.yml:/etc/prometheus/alerts.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    profiles:
      - observability

  grafana:
    image: grafana/grafana:10.2.0
    container_name: grafana
    ports:
      - "3001:3000"
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning
      - ./grafana/dashboards:/var/lib/grafana/dashboards
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-admin}
      - GF_USERS_ALLOW_SIGN_UP=false
    depends_on:
      - prometheus
    profiles:
      - observability

volumes:
  postgres_data:
  prometheus_data:
  grafana_data:
```

### 10.2 Environment Variables

```env
# .env

# OpenSky API
OPENSKY_USERNAME=your_username
OPENSKY_PASSWORD=your_password

# Ingestion Mode: live | replay
OPENSKY_MODE=live
REPLAY_FILE=fixtures/opensky_nyc_sample.jsonl
REPLAY_SPEED=1.0

# Bounding Box (NYC Metro)
BBOX_LAT_MIN=40.40
BBOX_LAT_MAX=41.20
BBOX_LON_MIN=-74.50
BBOX_LON_MAX=-73.50

# Polling
POLL_INTERVAL_SECONDS=10

# Kafka/Redpanda
REDPANDA_BROKER=redpanda:9092
KAFKA_TOPIC_STATE=flights.state
KAFKA_TOPIC_UPDATES=flights.updates
KAFKA_TOPIC_ANOMALIES=flights.anomalies

# Backend
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000

# Database (Phase 2)
DATABASE_URL=postgresql://skysentinel:skysentinel@postgres:5432/skysentinel

# Observability
PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc

# Security
POSTGRES_PASSWORD=skysentinel
GRAFANA_PASSWORD=admin
```

---

## 11. File Structure (Final)

```
flyinganomaly/
├── docker-compose.yml
├── .env
├── .env.example
├── README.md
│
├── docs/
│   ├── final_architecture.md      # This document
│   ├── final_phase1.md
│   └── final_phase2.md
│
├── static/
│   └── airports.geojson
│
├── fixtures/
│   └── opensky_nyc_sample.jsonl   # Replay data
│
├── ingestion/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── producer_flight.py
│   └── replay.py
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── consumer.py
│   ├── models.py
│   ├── websocket.py
│   └── metrics.py
│
├── processing/                    # Phase 2
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pipeline.py
│   ├── anomaly_detector.py
│   ├── smoothing.py
│   ├── validation.py
│   └── db_writer.py
│
├── database/
│   └── init.sql
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── components/
│       │   ├── FlightGlobe.tsx
│       │   ├── FlightFilters.tsx
│       │   ├── StatusBar.tsx
│       │   └── FlightTooltip.tsx
│       ├── hooks/
│       │   ├── useFlightStream.ts
│       │   └── useFlightState.ts
│       ├── types/
│       │   └── flight.ts
│       └── utils/
│           ├── interpolation.ts
│           └── msgpack.ts
│
├── prometheus/
│   ├── prometheus.yml
│   └── alerts.yml
│
└── grafana/
    ├── provisioning/
    │   ├── datasources/
    │   │   └── prometheus.yml
    │   └── dashboards/
    │       └── default.yml
    └── dashboards/
        └── skysentinel.json
```

Phase3:
Overlay the planes over an isometric view of NYC, generated by Gemini. with a projection matrix such to handle the projection from lat/lng to the pixel xy points referencing the 3 airports. 
either use proj4js or linear algebra to solve it.
Convert (Lat, Lon, Alt) -> (World X, Y, Z in meters).
Apply rotation (Camera looking North).
Apply tilt (Camera looking down ~45 degrees).
Project to 2D screen space.
Simplified approach (Linear Interpolation):
If the area is small (just NYC) and the angle is consistent, you might get away with a simple Affine Transformation. You just scale and rotate the lat/lon grid to match the pixels of the grid in your image.
