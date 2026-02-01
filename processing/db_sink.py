"""
Custom Bytewax sink for writing to PostgreSQL and publishing to Kafka.
"""

import logging
import time
from typing import Any

from bytewax.outputs import FixedPartitionedSink, StatefulSinkPartition

from db_writer import write_to_db, init_db
from kafka_publisher import publish_anomaly
from anomaly_detector import Anomaly
from metrics import MESSAGES_PROCESSED, ANOMALIES_DETECTED, DB_WRITE_LATENCY

logger = logging.getLogger(__name__)


class DatabaseSinkPartition(StatefulSinkPartition):
    """Sink partition for writing to database and Kafka."""
    
    def __init__(self):
        # Initialize database connection
        init_db()
        logger.info("Database sink partition initialized")
    
    def write_batch(self, items: list[tuple[Any, Any]]):
        """Write batch of (icao24, (flight, anomalies)) tuples."""
        for icao24, (flight, anomalies) in items:
            if not icao24 or not flight:
                continue
            
            try:
                # Track processing metrics
                MESSAGES_PROCESSED.inc()
                
                # Track anomalies detected
                for anomaly in anomalies:
                    ANOMALIES_DETECTED.labels(
                        anomaly_type=anomaly.anomaly_type.value,
                        severity=anomaly.severity.value
                    ).inc()
                
                # Write to database with latency tracking
                start_time = time.time()
                write_to_db(flight, anomalies)
                DB_WRITE_LATENCY.observe(time.time() - start_time)
                
                # Publish anomaly events
                for anomaly in anomalies:
                    publish_anomaly(anomaly)
                    
            except Exception as e:
                logger.error(f"Error processing flight {icao24}: {e}", exc_info=True)
    
    def snapshot(self):
        """No state to snapshot."""
        return None
    
    def close(self):
        """Cleanup on close."""
        pass


class DatabaseSink(FixedPartitionedSink):
    """Custom sink for database writes."""
    
    def list_parts(self):
        """Single partition for database writes."""
        return ["db"]
    
    def build_part(self, step_id: str, for_part: str, resume_state):
        """Build sink partition."""
        return DatabaseSinkPartition()
