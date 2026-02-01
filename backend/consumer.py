"""
Kafka consumer for flights.state topic with FlightCache and out-of-order rejection.
"""

import os
import sys
import json
import logging
import threading
from typing import Dict, Optional
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for contracts import
sys.path.insert(0, str(Path(__file__).parent.parent))

from confluent_kafka import Consumer, KafkaError, KafkaException
from models import FlightPayload
from metrics import MESSAGES_PROCESSED, MESSAGES_REJECTED, FLIGHTS_CACHED
from contracts.constants import MESSAGE_TYPE_FLIGHT_STATE
from contracts.validation import validate_flight_state_envelope

logger = logging.getLogger(__name__)

REDPANDA_BROKER = os.getenv("REDPANDA_BROKER", "redpanda:9092")
KAFKA_TOPIC_STATE = os.getenv("KAFKA_TOPIC_STATE", "flights.state")
WS_STALE_THRESHOLD_SECONDS = int(os.getenv("WS_STALE_THRESHOLD_SECONDS", "60"))


class FlightCache:
    """
    In-memory cache for flight states with out-of-order rejection.
    
    Maintains icao24 -> (FlightPayload, last_contact_unix) mapping.
    Rejects messages if last_contact_unix is older than cached value.
    """
    
    def __init__(self):
        self._cache: Dict[str, tuple[FlightPayload, int]] = {}
        self._lock = threading.RLock()
        self._sequence = 0
    
    def update(self, flight: FlightPayload) -> bool:
        """
        Update cache with new flight state.
        
        Returns:
            True if update was accepted, False if rejected (out-of-order)
        """
        icao24 = flight.icao24
        last_contact = flight.last_contact_unix
        
        with self._lock:
            if icao24 in self._cache:
                cached_flight, cached_last_contact = self._cache[icao24]
                
                # Reject if message is older than cached
                if last_contact < cached_last_contact:
                    MESSAGES_REJECTED.labels(reason="out_of_order").inc()
                    logger.debug(
                        f"Rejected out-of-order message for {icao24}: "
                        f"cached={cached_last_contact}, received={last_contact}"
                    )
                    return False
            
            # Accept update
            self._cache[icao24] = (flight, last_contact)
            self._sequence += 1
            FLIGHTS_CACHED.set(len(self._cache))
            return True
    
    def remove_stale(self, current_time: int) -> list[str]:
        """
        Remove flights that haven't been updated recently.
        
        Returns:
            List of icao24 values that were removed
        """
        removed = []
        threshold = current_time - WS_STALE_THRESHOLD_SECONDS
        
        with self._lock:
            to_remove = []
            for icao24, (flight, last_contact) in self._cache.items():
                if last_contact < threshold:
                    to_remove.append(icao24)
            
            for icao24 in to_remove:
                del self._cache[icao24]
                removed.append(icao24)
            
            if removed:
                FLIGHTS_CACHED.set(len(self._cache))
                logger.info(f"Removed {len(removed)} stale flights")
        
        return removed
    
    def get_all(self) -> Dict[str, FlightPayload]:
        """Get all cached flights."""
        with self._lock:
            return {icao24: flight for icao24, (flight, _) in self._cache.items()}
    
    def get_sequence(self) -> int:
        """Get current sequence number."""
        with self._lock:
            return self._sequence
    
    def size(self) -> int:
        """Get cache size."""
        with self._lock:
            return len(self._cache)


class FlightConsumer:
    """Kafka consumer for flights.state topic."""
    
    def __init__(self, cache: FlightCache):
        self.cache = cache
        self.consumer = None
        self.running = False
        self._thread = None
    
    def _create_consumer(self) -> Consumer:
        """Create Kafka consumer."""
        config = {
            'bootstrap.servers': REDPANDA_BROKER,
            'group.id': 'skysentinel-backend',
            'auto.offset.reset': 'earliest',  # Start from beginning on first run
            'enable.auto.commit': True,
            'auto.commit.interval.ms': 1000,
        }
        return Consumer(config)
    
    def _deserialize_message(self, msg_value: bytes) -> Optional[FlightPayload]:
        """Deserialize Kafka message to FlightPayload with validation."""
        try:
            envelope_dict = json.loads(msg_value.decode('utf-8'))
            
            # Validate envelope against schema
            is_valid, envelope, error = validate_flight_state_envelope(envelope_dict)
            if not is_valid:
                logger.warning(f"Invalid envelope: {error}")
                MESSAGES_REJECTED.labels(reason="schema_validation_failed").inc()
                return None
            
            # Validate message type
            if envelope.type != MESSAGE_TYPE_FLIGHT_STATE:
                logger.warning(f"Unexpected message type: {envelope.type}")
                MESSAGES_REJECTED.labels(reason="wrong_message_type").inc()
                return None
            
            # Convert validated envelope payload to FlightPayload
            payload_dict = envelope.payload.model_dump()
            flight = FlightPayload(**payload_dict)
            return flight
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON: {e}")
            MESSAGES_REJECTED.labels(reason="invalid_json").inc()
            return None
        except Exception as e:
            logger.error(f"Failed to deserialize message: {e}")
            MESSAGES_REJECTED.labels(reason="deserialization_error").inc()
            return None
    
    def _consume_loop(self):
        """Main consumption loop."""
        logger.info(f"Starting consumer for topic: {KAFKA_TOPIC_STATE}")
        
        self.consumer = self._create_consumer()
        self.consumer.subscribe([KAFKA_TOPIC_STATE])
        
        try:
            while self.running:
                msg = self.consumer.poll(timeout=1.0)
                
                if msg is None:
                    continue
                
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        # End of partition event - not an error
                        continue
                    else:
                        logger.error(f"Consumer error: {msg.error()}")
                        continue
                
                # Deserialize and process message
                flight = self._deserialize_message(msg.value())
                if flight:
                    self.cache.update(flight)
                    MESSAGES_PROCESSED.inc()
        
        except KafkaException as e:
            logger.error(f"Kafka exception: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in consumer loop: {e}")
        finally:
            if self.consumer:
                self.consumer.close()
                logger.info("Consumer closed")
    
    def start(self):
        """Start consumer in background thread."""
        if self.running:
            logger.warning("Consumer already running")
            return
        
        self.running = True
        self._thread = threading.Thread(target=self._consume_loop, daemon=True)
        self._thread.start()
        logger.info("Consumer started")
    
    def stop(self):
        """Stop consumer."""
        if not self.running:
            return
        
        self.running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Consumer stopped")
