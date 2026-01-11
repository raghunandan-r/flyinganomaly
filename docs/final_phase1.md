# Phase 1: Real-Time Flight Visualization (Final Implementation Guide)

**Objective:** Display live commercial aircraft positions on a 3D globe for the NYC metro area with smooth animation, compelling UX, and production-ready architecture.

**Canonical Reference:** `docs/final_architecture.md`

---

## 1. Phase 1 Scope

### 1.1 In Scope
- ✅ Live flight positions on interactive 3D globe
- ✅ Real-time updates via WebSocket (JSON + optional MessagePack)
- ✅ Smooth animation via Globe.gl transitions
- ✅ Ghost interpolation (visual data freshness indicator)
- ✅ Cockpit View (camera lock on selected aircraft)
- ✅ Lightweight filters (altitude, on-ground, callsign search)
- ✅ Replay mode for demos/testing without API credentials
- ✅ Prometheus metrics for observability
- ✅ Delta updates (only send changes, not full snapshots)

### 1.2 Out of Scope (Phase 2)
- ❌ PostgreSQL database
- ❌ Historical tracking / flight trails
- ❌ Anomaly detection
- ❌ Bytewax stream processing
- ❌ Time travel playback

---

## 2. System Architecture

```
┌─────────────────────┐
│     OpenSky API     │
│   (Bounding Box)    │
└──────────┬──────────┘
           │ HTTP (10s poll)
           ▼
┌─────────────────────┐
│   Flight Producer   │──────────────────────────────────────┐
│  (Python + Kafka)   │                                      │
└──────────┬──────────┘                                      │
           │                                                 │
           │ Kafka                                           │ Kafka
           ▼                                                 ▼
┌─────────────────────┐                           ┌─────────────────────┐
│   flights.state     │                           │   flights.updates   │
│    (Compacted)      │                           │   (Append-only)     │
│  Latest per ICAO24  │                           │   For Phase 2       │
└──────────┬──────────┘                           └─────────────────────┘
           │
           │ Single Consumer
           ▼
┌─────────────────────┐
│   FastAPI Backend   │
│  (Realtime Hub)     │
│  - In-memory cache  │
│  - WS broadcaster   │
│  - /metrics         │
└──────────┬──────────┘
           │ WebSocket (JSON/MessagePack)
           │ - snapshot on connect
           │ - delta updates @ 2-5Hz
           ▼
┌─────────────────────┐
│   React Frontend    │
│   (Globe.gl)        │
│  - Ghost interp.    │
│  - Cockpit View     │
│  - Filters          │
└─────────────────────┘
```

**Key Design Decisions:**
1. **No database in Phase 1.** UI is powered entirely by `flights.state` (compacted Kafka topic).
2. **One consumer per backend instance.** Backend consumes once and broadcasts to many WS clients.
3. **Dual-topic publishing.** Producer writes to both `flights.state` (for UI) and `flights.updates` (for Phase 2) simultaneously.
4. **Delta updates.** After initial snapshot, only changed flights + removals are sent.

---

## 3. Environment Configuration

### 3.1 `.env` File

```env
# ============================================
# PHASE 1 CONFIGURATION
# ============================================

# --- OpenSky API ---
OPENSKY_USERNAME=your_username
OPENSKY_PASSWORD=your_password

# --- Ingestion Mode ---
# live: Poll OpenSky API in real-time
# replay: Publish from fixture file (for demos/tests)
OPENSKY_MODE=live
REPLAY_FILE=fixtures/opensky_nyc_sample.jsonl
REPLAY_SPEED=1.0

# --- Bounding Box (NYC Metro, ~100km radius) ---
# Covers: JFK, LGA, EWR, TEB, HPN
BBOX_LAT_MIN=40.40
BBOX_LAT_MAX=41.20
BBOX_LON_MIN=-74.50
BBOX_LON_MAX=-73.50

# --- Polling ---
POLL_INTERVAL_SECONDS=10

# --- Kafka/Redpanda ---
REDPANDA_BROKER=redpanda:9092
KAFKA_TOPIC_STATE=flights.state
KAFKA_TOPIC_UPDATES=flights.updates
KAFKA_CLIENT_ID=skysentinel

# --- Backend ---
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000

# --- WebSocket ---
WS_DELTA_INTERVAL_MS=200
WS_STALE_THRESHOLD_SECONDS=60

# --- Observability ---
PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
```

### 3.2 `.env.example`

Copy this to `.env` and fill in credentials:

```env
OPENSKY_USERNAME=
OPENSKY_PASSWORD=
OPENSKY_MODE=live
BBOX_LAT_MIN=40.40
BBOX_LAT_MAX=41.20
BBOX_LON_MIN=-74.50
BBOX_LON_MAX=-73.50
POLL_INTERVAL_SECONDS=10
REDPANDA_BROKER=redpanda:9092
KAFKA_TOPIC_STATE=flights.state
KAFKA_TOPIC_UPDATES=flights.updates
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
```

---

## 4. Component Implementation

### 4.1 Docker Compose (Phase 1)

**File:** `docker-compose.yml`

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

  producer:
    build:
      context: ./ingestion
      dockerfile: Dockerfile
    container_name: flight_producer
    env_file: .env
    volumes:
      - ./fixtures:/app/fixtures:ro
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

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: frontend_app
    ports:
      - "3000:3000"
    environment:
      - VITE_WS_URL=ws://localhost:8000/ws/flights
      - VITE_API_URL=http://localhost:8000
    depends_on:
      - backend
```

---

### 4.2 Flight Producer

**Directory:** `ingestion/`

**Files:**
```
ingestion/
├── Dockerfile
├── requirements.txt
├── producer_flight.py      # Main entry point
├── opensky_client.py       # API client with retry logic
├── replay.py               # Replay mode implementation
└── metrics.py              # Prometheus metrics
```

#### `requirements.txt`
```
requests>=2.31.0
confluent-kafka>=2.3.0
prometheus-client>=0.19.0
python-dotenv>=1.0.0
```

#### `Dockerfile`
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-u", "producer_flight.py"]
```

#### `producer_flight.py` (Complete Implementation)

```python
#!/usr/bin/env python3
"""
Flight Producer - Polls OpenSky API and publishes to Redpanda.

Modes:
- live: Poll OpenSky API in real-time
- replay: Publish from fixture file for demos/tests

Publishes to:
- flights.state (compacted) - Latest state for UI
- flights.updates (append-only) - Event log for Phase 2
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Iterator

import requests
from confluent_kafka import Producer, KafkaError
from prometheus_client import Counter, Histogram, Gauge, start_http_server

# ============================================
# Configuration
# ============================================

OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME")
OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD")
OPENSKY_MODE = os.getenv("OPENSKY_MODE", "live")
REPLAY_FILE = os.getenv("REPLAY_FILE", "fixtures/opensky_nyc_sample.jsonl")
REPLAY_SPEED = float(os.getenv("REPLAY_SPEED", "1.0"))

BBOX_LAT_MIN = float(os.getenv("BBOX_LAT_MIN", "40.40"))
BBOX_LAT_MAX = float(os.getenv("BBOX_LAT_MAX", "41.20"))
BBOX_LON_MIN = float(os.getenv("BBOX_LON_MIN", "-74.50"))
BBOX_LON_MAX = float(os.getenv("BBOX_LON_MAX", "-73.50"))

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))

REDPANDA_BROKER = os.getenv("REDPANDA_BROKER", "redpanda:9092")
KAFKA_TOPIC_STATE = os.getenv("KAFKA_TOPIC_STATE", "flights.state")
KAFKA_TOPIC_UPDATES = os.getenv("KAFKA_TOPIC_UPDATES", "flights.updates")

OPENSKY_API_URL = "https://opensky-network.org/api/states/all"

# ============================================
# Logging
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# ============================================
# Prometheus Metrics
# ============================================

POLLS_TOTAL = Counter('producer_polls_total', 'Total API poll attempts', ['status'])
POLL_LATENCY = Histogram('producer_poll_latency_seconds', 'API poll duration')
FLIGHTS_PUBLISHED = Counter('producer_flights_published_total', 'Flights published', ['topic'])
API_ERRORS = Counter('producer_api_errors_total', 'API errors', ['error_type'])
DEADLETTER_TOTAL = Counter('producer_deadletter_total', 'Invalid payloads')
CURRENT_FLIGHTS = Gauge('producer_current_flights', 'Flights in last poll')

# ============================================
# OpenSky Client
# ============================================

class OpenSkyClient:
    """Client for OpenSky Network API with retry logic."""
    
    def __init__(self, username: Optional[str], password: Optional[str]):
        self.auth = (username, password) if username and password else None
        self.session = requests.Session()
        if self.auth:
            self.session.auth = self.auth
    
    def fetch_states(self, bbox: dict) -> Optional[list]:
        """Fetch aircraft states for bounding box. Returns list or None on error."""
        params = {
            "lamin": bbox["lat_min"],
            "lamax": bbox["lat_max"],
            "lomin": bbox["lon_min"],
            "lomax": bbox["lon_max"]
        }
        
        try:
            with POLL_LATENCY.time():
                response = self.session.get(
                    OPENSKY_API_URL,
                    params=params,
                    timeout=30
                )
            
            if response.status_code == 200:
                POLLS_TOTAL.labels(status="success").inc()
                data = response.json()
                return data.get("states", [])
            
            elif response.status_code == 429:
                POLLS_TOTAL.labels(status="rate_limited").inc()
                API_ERRORS.labels(error_type="rate_limited").inc()
                logger.warning("Rate limited. Waiting 60s...")
                time.sleep(60)
                return None
            
            elif response.status_code == 401:
                POLLS_TOTAL.labels(status="auth_failed").inc()
                API_ERRORS.labels(error_type="auth_failed").inc()
                logger.critical("Authentication failed. Check credentials.")
                sys.exit(1)
            
            else:
                POLLS_TOTAL.labels(status="error").inc()
                API_ERRORS.labels(error_type=f"http_{response.status_code}").inc()
                logger.error(f"API error: {response.status_code}")
                return None
        
        except requests.exceptions.Timeout:
            POLLS_TOTAL.labels(status="timeout").inc()
            API_ERRORS.labels(error_type="timeout").inc()
            logger.error("API timeout")
            return None
        
        except requests.exceptions.RequestException as e:
            POLLS_TOTAL.labels(status="connection_error").inc()
            API_ERRORS.labels(error_type="connection").inc()
            logger.error(f"Connection error: {e}")
            return None

# ============================================
# Message Transformation
# ============================================

def transform_state(state: list, produced_at: str, bbox: dict) -> Optional[dict]:
    """Transform OpenSky state array to envelope format."""
    try:
        # OpenSky state indices
        icao24 = state[0]
        callsign = (state[1] or "").strip() or None
        origin_country = state[2]
        time_position = state[3]
        last_contact = state[4]
        longitude = state[5]
        latitude = state[6]
        baro_altitude = state[7]
        on_ground = state[8]
        velocity = state[9]
        true_track = state[10]
        vertical_rate = state[11]
        sensors = state[12]
        geo_altitude = state[13]
        squawk = state[14]
        spi = state[15]
        position_source = state[16]
        
        # Validate required fields
        if not icao24 or latitude is None or longitude is None:
            return None
        
        # Build payload
        payload = {
            "icao24": icao24.lower(),
            "callsign": callsign,
            "position": {
                "lat": latitude,
                "lon": longitude
            },
            "altitude_m": baro_altitude,
            "geo_altitude_m": geo_altitude,
            "velocity_mps": velocity,
            "heading_deg": true_track,
            "vertical_rate_mps": vertical_rate,
            "on_ground": on_ground,
            "squawk": squawk,
            "spi": spi,
            "time_position_unix": time_position,
            "last_contact_unix": last_contact
        }
        
        # Build envelope
        envelope = {
            "schema_version": 1,
            "type": "flight_state",
            "produced_at": produced_at,
            "source": {
                "provider": "opensky",
                "mode": OPENSKY_MODE,
                "bbox": bbox,
                "poll_interval_s": POLL_INTERVAL
            },
            "payload": payload
        }
        
        return envelope
    
    except (IndexError, TypeError) as e:
        logger.warning(f"Failed to transform state: {e}")
        DEADLETTER_TOTAL.inc()
        return None

# ============================================
# Kafka Producer
# ============================================

def create_producer() -> Producer:
    """Create Kafka producer with delivery confirmation."""
    config = {
        "bootstrap.servers": REDPANDA_BROKER,
        "client.id": "skysentinel-producer",
        "acks": "all",
        "retries": 3,
        "retry.backoff.ms": 1000
    }
    return Producer(config)

def delivery_callback(err, msg):
    """Callback for delivery confirmation."""
    if err:
        logger.error(f"Delivery failed: {err}")
    else:
        FLIGHTS_PUBLISHED.labels(topic=msg.topic()).inc()

# ============================================
# Replay Mode
# ============================================

def replay_iterator(filepath: str, speed: float) -> Iterator[list]:
    """
    Read recorded JSONL file and yield states with timing.
    
    File format: Each line is a JSON envelope from a previous recording.
    """
    logger.info(f"Replay mode: reading from {filepath} at {speed}x speed")
    
    last_ts = None
    
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            try:
                envelope = json.loads(line)
                payload = envelope.get("payload", {})
                
                # Simulate timing
                ts = payload.get("last_contact_unix", 0)
                if last_ts and ts > last_ts:
                    delay = (ts - last_ts) / speed
                    if delay > 0 and delay < 60:
                        time.sleep(delay)
                last_ts = ts
                
                # Yield as fake state array (transform will handle it)
                yield envelope
                
            except json.JSONDecodeError:
                continue

# ============================================
# Main Loop
# ============================================

def main():
    logger.info("=" * 50)
    logger.info("SkySentinel Flight Producer")
    logger.info(f"Mode: {OPENSKY_MODE}")
    logger.info(f"Bbox: ({BBOX_LAT_MIN}, {BBOX_LON_MIN}) to ({BBOX_LAT_MAX}, {BBOX_LON_MAX})")
    logger.info(f"Poll interval: {POLL_INTERVAL}s")
    logger.info(f"Broker: {REDPANDA_BROKER}")
    logger.info("=" * 50)
    
    # Start Prometheus metrics server
    start_http_server(8001)
    logger.info("Prometheus metrics available on :8001")
    
    # Initialize
    producer = create_producer()
    bbox = {
        "lat_min": BBOX_LAT_MIN,
        "lat_max": BBOX_LAT_MAX,
        "lon_min": BBOX_LON_MIN,
        "lon_max": BBOX_LON_MAX
    }
    
    if OPENSKY_MODE == "replay":
        # Replay mode
        for envelope in replay_iterator(REPLAY_FILE, REPLAY_SPEED):
            key = envelope["payload"]["icao24"].encode()
            value = json.dumps(envelope).encode()
            
            # Publish to both topics
            producer.produce(KAFKA_TOPIC_STATE, key=key, value=value, callback=delivery_callback)
            envelope["type"] = "flight_update"
            producer.produce(KAFKA_TOPIC_UPDATES, key=key, value=json.dumps(envelope).encode(), callback=delivery_callback)
            producer.poll(0)
        
        producer.flush()
        logger.info("Replay complete")
        return
    
    # Live mode
    client = OpenSkyClient(OPENSKY_USERNAME, OPENSKY_PASSWORD)
    
    while True:
        loop_start = time.time()
        
        states = client.fetch_states(bbox)
        
        if states:
            produced_at = datetime.now(timezone.utc).isoformat()
            count = 0
            
            for state in states:
                envelope = transform_state(state, produced_at, bbox)
                if envelope:
                    key = envelope["payload"]["icao24"].encode()
                    value = json.dumps(envelope).encode()
                    
                    # Publish to state topic (compacted)
                    producer.produce(
                        KAFKA_TOPIC_STATE,
                        key=key,
                        value=value,
                        callback=delivery_callback
                    )
                    
                    # Publish to updates topic (append-only)
                    envelope_update = envelope.copy()
                    envelope_update["type"] = "flight_update"
                    producer.produce(
                        KAFKA_TOPIC_UPDATES,
                        key=key,
                        value=json.dumps(envelope_update).encode(),
                        callback=delivery_callback
                    )
                    
                    count += 1
            
            producer.poll(0)
            CURRENT_FLIGHTS.set(count)
            logger.info(f"Published {count} flights")
        
        # Wait for next poll
        elapsed = time.time() - loop_start
        sleep_time = max(0, POLL_INTERVAL - elapsed)
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
