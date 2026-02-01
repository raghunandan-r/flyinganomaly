"""
Kafka consumer for flights.anomalies topic.
Consumes anomaly events and broadcasts them via WebSocket.
"""

import os
import json
import logging
import threading
from typing import Optional, Callable
from datetime import datetime, timezone

from confluent_kafka import Consumer, KafkaError, KafkaException
from metrics import MESSAGES_PROCESSED, MESSAGES_REJECTED

logger = logging.getLogger(__name__)

REDPANDA_BROKER = os.getenv("REDPANDA_BROKER", "redpanda:9092")
KAFKA_TOPIC_ANOMALIES = os.getenv("KAFKA_TOPIC_ANOMALIES", "flights.anomalies")


class AnomalyConsumer:
    """Kafka consumer for flights.anomalies topic."""
    
    def __init__(self, on_anomaly: Callable[[dict], None]):
        """
        Initialize anomaly consumer.
        
        Args:
            on_anomaly: Callback function called when anomaly is received.
                        Receives anomaly payload dict.
        """
        self.on_anomaly = on_anomaly
        self.consumer = None
        self.running = False
        self._thread = None
    
    def _create_consumer(self) -> Consumer:
        """Create Kafka consumer."""
        config = {
            'bootstrap.servers': REDPANDA_BROKER,
            'group.id': 'skysentinel-backend-anomalies',
            'auto.offset.reset': 'latest',  # Start from latest (don't replay old anomalies)
            'enable.auto.commit': True,
            'auto.commit.interval.ms': 1000,
        }
        return Consumer(config)
    
    def _deserialize_message(self, msg_value: bytes) -> Optional[dict]:
        """Deserialize Kafka message to anomaly payload."""
        try:
            envelope = json.loads(msg_value.decode('utf-8'))
            
            # Validate envelope structure
            if envelope.get('type') != 'anomaly_event':
                logger.warning(f"Unexpected message type: {envelope.get('type')}")
                return None
            
            payload = envelope.get('payload')
            if not payload:
                logger.warning("Missing payload in envelope")
                return None
            
            # Validate required fields
            if not payload.get('icao24'):
                logger.warning("Missing icao24 in anomaly payload")
                return None
            
            return payload
        
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
        logger.info(f"Starting anomaly consumer for topic: {KAFKA_TOPIC_ANOMALIES}")
        
        self.consumer = self._create_consumer()
        self.consumer.subscribe([KAFKA_TOPIC_ANOMALIES])
        
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
                payload = self._deserialize_message(msg.value())
                if payload:
                    try:
                        self.on_anomaly(payload)
                        MESSAGES_PROCESSED.inc()
                        logger.debug(f"Processed anomaly for {payload.get('icao24')}")
                    except Exception as e:
                        logger.error(f"Error handling anomaly: {e}", exc_info=True)
        
        except KafkaException as e:
            logger.error(f"Kafka exception: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in consumer loop: {e}")
        finally:
            if self.consumer:
                self.consumer.close()
                logger.info("Anomaly consumer closed")
    
    def start(self):
        """Start consumer in background thread."""
        if self.running:
            logger.warning("Anomaly consumer already running")
            return
        
        self.running = True
        self._thread = threading.Thread(target=self._consume_loop, daemon=True)
        self._thread.start()
        logger.info("Anomaly consumer started")
    
    def stop(self):
        """Stop consumer."""
        if not self.running:
            return
        
        self.running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Anomaly consumer stopped")
