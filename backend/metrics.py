"""
Prometheus metrics for the backend service.
"""

import os
from fastapi.responses import Response
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client.multiprocess import MultiProcessCollector
from prometheus_client.registry import REGISTRY


# Backend metrics as defined in architecture docs
KAFKA_CONSUMER_LAG = Gauge(
    'backend_kafka_consumer_lag',
    'Consumer lag',
    ['topic', 'partition']
)

FLIGHTS_CACHED = Gauge(
    'backend_flights_cached',
    'Current flights in cache'
)

WEBSOCKET_CONNECTIONS = Gauge(
    'backend_websocket_connections',
    'Active WebSocket connections'
)

WEBSOCKET_MESSAGES_SENT = Counter(
    'backend_websocket_messages_sent_total',
    'Messages sent by type',
    ['type']  # snapshot, delta, anomaly
)

HTTP_REQUESTS = Counter(
    'backend_http_requests_total',
    'HTTP requests',
    ['method', 'path', 'status']
)

MESSAGES_PROCESSED = Counter(
    'backend_messages_processed_total',
    'Kafka messages processed'
)

MESSAGES_REJECTED = Counter(
    'backend_messages_rejected_total',
    'Messages rejected (out-of-order)',
    ['reason']
)


async def get_metrics():
    """FastAPI handler for /metrics endpoint."""
    if 'PROMETHEUS_MULTIPROC_DIR' in os.environ:
        # Multi-process mode (for production)
        registry = REGISTRY
        collector = MultiProcessCollector(registry)
        output = generate_latest(collector)
    else:
        # Single-process mode (for development)
        output = generate_latest()
    
    return Response(content=output, media_type=CONTENT_TYPE_LATEST)
