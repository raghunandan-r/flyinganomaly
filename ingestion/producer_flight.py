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
from pathlib import Path

# Add parent directory to path for contracts import
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from confluent_kafka import Producer, KafkaError
from prometheus_client import Counter, Histogram, Gauge, start_http_server

from contracts.constants import (
    KAFKA_TOPIC_STATE,
    KAFKA_TOPIC_UPDATES,
    MESSAGE_TYPE_FLIGHT_STATE,
    MESSAGE_TYPE_FLIGHT_UPDATE,
    SCHEMA_VERSION,
    PROVIDER_OPENSKY,
    MODE_LIVE,
    MODE_REPLAY,
)
from contracts.validation import (
    FlightStateEnvelope,
    FlightUpdateEnvelope,
    validate_flight_state_envelope,
    validate_flight_update_envelope,
)

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
# Use constants from contracts, but allow override via env
_TOPIC_STATE = os.getenv("KAFKA_TOPIC_STATE", KAFKA_TOPIC_STATE)
_TOPIC_UPDATES = os.getenv("KAFKA_TOPIC_UPDATES", KAFKA_TOPIC_UPDATES)
KAFKA_TOPIC_STATE = _TOPIC_STATE
KAFKA_TOPIC_UPDATES = _TOPIC_UPDATES

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
# OpenSky Client (OAuth2 Client Credentials Flow)
# ============================================

OPENSKY_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
TOKEN_REFRESH_BUFFER_SECONDS = 300  # Refresh 5 minutes before expiry (tokens last 30 min)

# Token metrics
TOKEN_REFRESHES = Counter('producer_token_refreshes_total', 'OAuth2 token refresh attempts', ['status'])


class OpenSkyClient:
    """Client for OpenSky Network API with OAuth2 authentication and retry logic."""
    
    def __init__(self, client_id: Optional[str], client_secret: Optional[str]):
        """
        Initialize OpenSky client with OAuth2 credentials.
        
        Args:
            client_id: OAuth2 client ID (from OPENSKY_USERNAME env var)
            client_secret: OAuth2 client secret (from OPENSKY_PASSWORD env var)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = requests.Session()
        
        # OAuth2 token state
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0  # Unix timestamp when token expires
        
        # Obtain initial token if credentials provided
        if self.client_id and self.client_secret:
            self._refresh_token()
    
    def _refresh_token(self) -> bool:
        """
        Obtain a new OAuth2 access token using client credentials flow.
        
        Returns:
            True if token was successfully obtained, False otherwise.
        """
        if not self.client_id or not self.client_secret:
            logger.warning("Cannot refresh token: missing client credentials")
            return False
        
        try:
            response = requests.post(
                OPENSKY_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret
                },
                timeout=30
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self._access_token = token_data.get("access_token")
                
                # Calculate expiry time (default 30 min = 1800 seconds)
                expires_in = token_data.get("expires_in", 1800)
                self._token_expires_at = time.time() + expires_in
                
                TOKEN_REFRESHES.labels(status="success").inc()
                logger.info(
                    f"OAuth2 token obtained successfully. "
                    f"Expires in {expires_in}s ({expires_in // 60} min)"
                )
                return True
            else:
                TOKEN_REFRESHES.labels(status="failed").inc()
                logger.error(
                    f"Failed to obtain OAuth2 token: HTTP {response.status_code} - {response.text}"
                )
                return False
                
        except requests.exceptions.RequestException as e:
            TOKEN_REFRESHES.labels(status="error").inc()
            logger.error(f"Token refresh request failed: {e}")
            return False
    
    def _ensure_valid_token(self) -> bool:
        """
        Ensure we have a valid (non-expired) token.
        Refreshes the token if it's expired or about to expire.
        
        Returns:
            True if we have a valid token, False otherwise.
        """
        if not self.client_id or not self.client_secret:
            return False  # No credentials, will use anonymous access
        
        # Check if token needs refresh (expired or expiring soon)
        time_until_expiry = self._token_expires_at - time.time()
        
        if self._access_token is None or time_until_expiry <= TOKEN_REFRESH_BUFFER_SECONDS:
            if self._access_token is None:
                logger.info("No token available, obtaining new token...")
            else:
                logger.info(
                    f"Token expiring in {time_until_expiry:.0f}s, refreshing proactively..."
                )
            return self._refresh_token()
        
        return True
    
    def _get_auth_headers(self) -> dict:
        """Get authorization headers for API requests."""
        if self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        return {}
    
    def fetch_states(self, bbox: dict, retry_on_401: bool = True) -> Optional[list]:
        """
        Fetch aircraft states for bounding box. Returns list or None on error.
        
        Args:
            bbox: Bounding box with lat_min, lat_max, lon_min, lon_max
            retry_on_401: If True, refresh token and retry on 401 response
        """
        # Ensure we have a valid token before making the request
        self._ensure_valid_token()
        
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
                    headers=self._get_auth_headers(),
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
                
                if retry_on_401 and self.client_id and self.client_secret:
                    # Token may have expired (server-side) - try refreshing once
                    logger.warning("401 Unauthorized - attempting token refresh...")
                    if self._refresh_token():
                        # Retry the request with new token (but don't retry again on failure)
                        return self.fetch_states(bbox, retry_on_401=False)
                
                logger.error(
                    "Authentication failed. Token refresh unsuccessful or no credentials. "
                    "Check your client_id (OPENSKY_USERNAME) and client_secret (OPENSKY_PASSWORD)."
                )
                return None
            
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
    """Transform OpenSky state array to FlightEnvelope format."""
    try:
        # OpenSky state indices (see Architecture Section 3.2)
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
        position_source = state[16] if len(state) > 16 else None
        
        # Validate required fields
        if not icao24 or latitude is None or longitude is None:
            return None
        
        # Build FlightPayload (Architecture Section 3.2)
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
        
        # Build FlightEnvelope (Architecture Section 3.1)
        envelope_dict = {
            "schema_version": SCHEMA_VERSION,
            "type": MESSAGE_TYPE_FLIGHT_STATE,
            "produced_at": produced_at,
            "source": {
                "provider": PROVIDER_OPENSKY,
                "mode": OPENSKY_MODE if OPENSKY_MODE in (MODE_LIVE, MODE_REPLAY) else MODE_LIVE,
                "bbox": bbox,
                "poll_interval_s": POLL_INTERVAL
            },
            "payload": payload
        }
        
        # Validate envelope before returning
        is_valid, envelope, error = validate_flight_state_envelope(envelope_dict)
        if not is_valid:
            logger.warning(f"Invalid envelope generated: {error}")
            DEADLETTER_TOTAL.inc()
            return None
        
        return envelope_dict
    
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

def replay_iterator(filepath: str, speed: float) -> Iterator[dict]:
    """
    Read recorded JSONL file and yield envelopes with timing preserved.
    
    File format: Each line is a JSON FlightEnvelope from a previous recording.
    
    Timing logic:
    - Uses last_contact_unix from payload to determine relative timing
    - First message establishes baseline timestamp
    - Subsequent messages are delayed based on time difference from previous message
    - Speed multiplier adjusts replay rate (1.0 = real-time, 2.0 = 2x speed)
    - Ensures deterministic, consistent replay behavior
    """
    logger.info(f"Replay mode: reading from {filepath} at {speed}x speed")
    
    if not os.path.exists(filepath):
        logger.error(f"Replay file not found: {filepath}")
        sys.exit(1)
    
    # Track timing state
    first_ts = None
    last_ts = None
    replay_start_time = None
    
    with open(filepath, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                envelope = json.loads(line)
                payload = envelope.get("payload", {})
                
                # Get timestamp from payload
                ts = payload.get("last_contact_unix")
                
                if ts is None:
                    # No timestamp - yield immediately
                    logger.debug(f"Line {line_num}: No timestamp, yielding immediately")
                    yield envelope
                    continue
                
                # Initialize timing on first valid timestamp
                if first_ts is None:
                    first_ts = ts
                    last_ts = ts
                    replay_start_time = time.time()
                    logger.info(f"Replay started at timestamp {first_ts}")
                    yield envelope
                    continue
                
                # Calculate delay based on time difference from previous message
                if ts >= last_ts:
                    # Normal case: message is newer or same time
                    time_diff = ts - last_ts
                    delay_seconds = time_diff / speed
                    
                    # Cap delay at reasonable maximum (60 seconds) to avoid long waits
                    if delay_seconds > 60:
                        logger.warning(
                            f"Large time gap detected: {delay_seconds:.1f}s "
                            f"(capped at 60s). Timestamp jump: {last_ts} -> {ts}"
                        )
                        delay_seconds = 60
                    
                    # Only sleep if there's a meaningful delay (> 10ms)
                    if delay_seconds > 0.01:
                        time.sleep(delay_seconds)
                    
                    last_ts = ts
                else:
                    # Out-of-order message: log warning but yield immediately
                    logger.warning(
                        f"Out-of-order timestamp detected at line {line_num}: "
                        f"{ts} < {last_ts} (diff: {last_ts - ts}s). Yielding immediately."
                    )
                    # Don't update last_ts for out-of-order messages
                
                yield envelope
                
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON on line {line_num}: {e}")
                continue
            except Exception as e:
                logger.warning(f"Error processing line {line_num}: {e}")
                continue
    
    # Log replay completion stats
    if first_ts and last_ts:
        total_replay_time = (last_ts - first_ts) / speed
        actual_wall_time = time.time() - replay_start_time if replay_start_time else 0
        logger.info(
            f"Replay complete. Timestamp range: {first_ts} -> {last_ts} "
            f"({last_ts - first_ts}s). Replay time: {total_replay_time:.1f}s. "
            f"Actual wall time: {actual_wall_time:.1f}s"
        )

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
        # Replay mode: read from file and publish with timing
        logger.info(f"Starting replay from {REPLAY_FILE}")
        count = 0
        
        for envelope in replay_iterator(REPLAY_FILE, REPLAY_SPEED):
            payload = envelope.get("payload", {})
            icao24 = payload.get("icao24")
            
            if not icao24:
                logger.warning("Skipping envelope without icao24")
                continue
            
            key = icao24.encode()
            
            # Validate and publish to flights.state (compacted) with flight_state type
            envelope_state = envelope.copy()
            envelope_state["type"] = MESSAGE_TYPE_FLIGHT_STATE
            is_valid, validated_state, error = validate_flight_state_envelope(envelope_state)
            if not is_valid:
                logger.warning(f"Invalid state envelope: {error}")
                DEADLETTER_TOTAL.inc()
                continue
            value_state = json.dumps(envelope_state).encode()
            producer.produce(
                KAFKA_TOPIC_STATE,
                key=key,
                value=value_state,
                callback=delivery_callback
            )
            
            # Validate and publish to flights.updates (append-only) with flight_update type
            envelope_update = envelope.copy()
            envelope_update["type"] = MESSAGE_TYPE_FLIGHT_UPDATE
            is_valid, validated_update, error = validate_flight_update_envelope(envelope_update)
            if not is_valid:
                logger.warning(f"Invalid update envelope: {error}")
                DEADLETTER_TOTAL.inc()
                continue
            value_update = json.dumps(envelope_update).encode()
            producer.produce(
                KAFKA_TOPIC_UPDATES,
                key=key,
                value=value_update,
                callback=delivery_callback
            )
            
            producer.poll(0)
            count += 1
        
        producer.flush()
        CURRENT_FLIGHTS.set(count)
        logger.info(f"Replay complete. Published {count} flights")
        return
    
    # Live mode: poll OpenSky API with OAuth2 authentication
    if not OPENSKY_USERNAME or not OPENSKY_PASSWORD:
        logger.warning(
            "OpenSky OAuth2 credentials not provided. Using anonymous access (rate-limited). "
            "Set OPENSKY_USERNAME (client_id) and OPENSKY_PASSWORD (client_secret) for authenticated access."
        )
    else:
        logger.info(
            f"Using OAuth2 client credentials flow with client_id: {OPENSKY_USERNAME[:8]}..."
        )
    
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
                    payload = envelope.get("payload", {})
                    icao24 = payload.get("icao24")
                    
                    if not icao24:
                        continue
                    
                    key = icao24.encode()
                    value = json.dumps(envelope).encode()
                    
                    # Validate and publish to flights.state (compacted) - latest state per aircraft
                    envelope_state = envelope.copy()
                    envelope_state["type"] = MESSAGE_TYPE_FLIGHT_STATE
                    is_valid, validated_state, error = validate_flight_state_envelope(envelope_state)
                    if not is_valid:
                        logger.warning(f"Invalid state envelope: {error}")
                        DEADLETTER_TOTAL.inc()
                        continue
                    value_state = json.dumps(envelope_state).encode()
                    producer.produce(
                        KAFKA_TOPIC_STATE,
                        key=key,
                        value=value_state,
                        callback=delivery_callback
                    )
                    
                    # Validate and publish to flights.updates (append-only) - event log
                    envelope_update = envelope.copy()
                    envelope_update["type"] = MESSAGE_TYPE_FLIGHT_UPDATE
                    is_valid, validated_update, error = validate_flight_update_envelope(envelope_update)
                    if not is_valid:
                        logger.warning(f"Invalid update envelope: {error}")
                        DEADLETTER_TOTAL.inc()
                        continue
                    value_update = json.dumps(envelope_update).encode()
                    producer.produce(
                        KAFKA_TOPIC_UPDATES,
                        key=key,
                        value=value_update,
                        callback=delivery_callback
                    )
                    
                    count += 1
            
            producer.poll(0)
            producer.flush()
            CURRENT_FLIGHTS.set(count)
            logger.info(f"Published {count} flights")
        
        # Wait for next poll
        elapsed = time.time() - loop_start
        sleep_time = max(0, POLL_INTERVAL - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)


if __name__ == "__main__":
    main()
