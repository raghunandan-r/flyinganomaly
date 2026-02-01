"""
Prometheus metrics for the processing service.
"""

from prometheus_client import Counter, Histogram

# Processing metrics as defined in Stream F requirements
MESSAGES_PROCESSED = Counter(
    'processing_messages_processed_total',
    'Total messages processed by the pipeline'
)

ANOMALIES_DETECTED = Counter(
    'processing_anomalies_detected_total',
    'Total anomalies detected',
    ['anomaly_type', 'severity']
)

DB_WRITE_LATENCY = Histogram(
    'processing_db_write_latency_seconds',
    'Database write latency',
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
