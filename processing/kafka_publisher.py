"""
Kafka publisher for anomaly events.
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

# Add parent directory to path for contracts import
sys.path.insert(0, str(Path(__file__).parent.parent))

from confluent_kafka import Producer

from anomaly_detector import Anomaly
from contracts.constants import (
    KAFKA_TOPIC_ANOMALIES,
    MESSAGE_TYPE_ANOMALY_EVENT,
    SCHEMA_VERSION,
    PROVIDER_SKYSENTINEL_PROCESSING,
)
from contracts.validation import validate_anomaly_event_envelope

logger = logging.getLogger(__name__)

REDPANDA_BROKER = os.getenv("REDPANDA_BROKER", "redpanda:9092")
# Use constant from contracts, but allow override via env
_TOPIC_ANOMALIES = os.getenv("KAFKA_TOPIC_ANOMALIES", KAFKA_TOPIC_ANOMALIES)
KAFKA_TOPIC_ANOMALIES = _TOPIC_ANOMALIES

# Producer instance (singleton)
_producer: Optional[Producer] = None


def get_producer() -> Producer:
    """Get or create Kafka producer."""
    global _producer
    if _producer is None:
        _producer = Producer({
            "bootstrap.servers": REDPANDA_BROKER,
            "client.id": "skysentinel-processor"
        })
    return _producer


def publish_anomaly(anomaly: Anomaly):
    """
    Publish anomaly event to Kafka topic.
    
    Publishes AnomalyEventEnvelope format.
    """
    producer = get_producer()
    
    # Create envelope dict
    envelope_dict = {
        "schema_version": SCHEMA_VERSION,
        "type": MESSAGE_TYPE_ANOMALY_EVENT,
        "produced_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "provider": PROVIDER_SKYSENTINEL_PROCESSING
        },
        "payload": {
            "icao24": anomaly.icao24,
            "callsign": anomaly.callsign,
            "anomaly_type": anomaly.anomaly_type.value,
            "severity": anomaly.severity.value,
            "detected_at": anomaly.detected_at.isoformat(),
            "position": anomaly.position,
            "details": anomaly.details
        }
    }
    
    # Validate envelope before publishing
    is_valid, validated_envelope, error = validate_anomaly_event_envelope(envelope_dict)
    if not is_valid:
        logger.error(f"Invalid anomaly envelope: {error}")
        return
    
    try:
        # Publish with icao24 as key for partitioning
        producer.produce(
            KAFKA_TOPIC_ANOMALIES,
            key=anomaly.icao24.encode() if isinstance(anomaly.icao24, str) else anomaly.icao24,
            value=json.dumps(envelope_dict),
            callback=lambda err, msg: logger.error(f"Failed to publish anomaly: {err}") if err else None
        )
        producer.poll(0)  # Trigger delivery callbacks
        
    except Exception as e:
        logger.error(f"Error publishing anomaly: {e}", exc_info=True)
