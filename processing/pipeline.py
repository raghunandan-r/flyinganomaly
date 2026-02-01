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
import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for contracts import
sys.path.insert(0, str(Path(__file__).parent.parent))

from bytewax.dataflow import Dataflow
from bytewax import operators as op
from bytewax.connectors.kafka import KafkaSource

from smoothing import FlightSmoother
from anomaly_detector import AnomalyDetector, Anomaly
from db_writer import init_db
from db_sink import DatabaseSink
from contracts.constants import MESSAGE_TYPE_FLIGHT_UPDATE
from contracts.validation import validate_flight_update_envelope

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
REDPANDA_BROKER = os.getenv("REDPANDA_BROKER", "redpanda:9092")
KAFKA_TOPIC_UPDATES = os.getenv("KAFKA_TOPIC_UPDATES", "flights.updates")


def deserialize(msg) -> tuple:
    """Deserialize Kafka message with validation. Returns (key, payload_dict)."""
    try:
        key = msg.key.decode() if msg.key else None
        envelope_dict = json.loads(msg.value.decode())
        
        # Validate envelope against schema
        is_valid, envelope, error = validate_flight_update_envelope(envelope_dict)
        if not is_valid:
            logger.warning(f"Invalid envelope: {error}")
            return (None, None)
        
        # Ensure correct message type
        if envelope.type != MESSAGE_TYPE_FLIGHT_UPDATE:
            logger.warning(f"Unexpected message type: {envelope.type}, expected {MESSAGE_TYPE_FLIGHT_UPDATE}")
            return (None, None)
        
        # Extract payload as dict
        payload = envelope.payload.model_dump()
        
        return (key, payload)
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, AttributeError) as e:
        logger.warning(f"Failed to deserialize message: {e}")
        return (None, None)


class ProcessingState:
    """Combined state for smoothing + anomaly detection."""
    
    def __init__(self):
        self.smoother: FlightSmoother | None = None
        self.detector: AnomalyDetector | None = None
    
    def process(self, flight: dict) -> tuple:
        """Process flight update. Returns (flight_dict, list_of_anomalies)."""
        icao24 = flight.get("icao24")
        if not icao24:
            return flight, []
        
        # Initialize on first use
        if self.smoother is None:
            self.smoother = FlightSmoother(icao24)
        if self.detector is None:
            self.detector = AnomalyDetector()
        
        # Ensure smoother has correct icao24
        if self.smoother.icao24 != icao24:
            self.smoother = FlightSmoother(icao24)
        
        # Smooth
        flight = self.smoother.process(flight)
        
        # Detect anomalies
        flight, anomalies = self.detector.process(flight)
        
        return flight, anomalies




# Build dataflow
flow = Dataflow("flight_processing")

# Initialize database connection
init_db()

# Input: Kafka
kafka_source = KafkaSource([REDPANDA_BROKER], [KAFKA_TOPIC_UPDATES])
input_stream = op.input("kafka_in", flow, kafka_source)

# Deserialize
deserialized_stream = op.map("deserialize", input_stream, deserialize)

# Filter invalid messages
filtered_stream = op.filter(
    "filter_valid",
    deserialized_stream,
    lambda kv: kv[0] is not None and kv[1] is not None and kv[1].get("icao24") is not None
)

# Extract icao24 as key for stateful processing
keyed_stream = op.map(
    "extract_key",
    filtered_stream,
    lambda kv: (kv[1].get("icao24", kv[0]), kv[1])
)

# Stateful processing (smoothing + anomaly detection)
def process_with_state(state: ProcessingState, flight: dict) -> tuple[ProcessingState, tuple]:
    """Process flight with stateful operations."""
    flight, anomalies = state.process(flight)
    return state, (flight, anomalies)

processed_stream = op.stateful_map(
    "process",
    keyed_stream,
    lambda: ProcessingState(),
    process_with_state
)

# Output: DB + Kafka
op.output("output", flow, processed_stream, DatabaseSink())
