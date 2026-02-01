#!/usr/bin/env python3
"""
Entry point for Bytewax stream processing pipeline.
"""

import os
import logging
import threading
from prometheus_client import start_http_server
from bytewax.execution import run_main

from pipeline import flow

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Prometheus metrics server port (matching prometheus/prometheus.yml scrape config)
METRICS_PORT = int(os.getenv("METRICS_PORT", "8080"))


def start_metrics_server():
    """Start Prometheus metrics server in background thread."""
    try:
        start_http_server(METRICS_PORT)
        logger.info(f"Prometheus metrics server started on port {METRICS_PORT}")
    except Exception as e:
        logger.error(f"Failed to start metrics server: {e}")


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("SkySentinel Processing Pipeline - Starting")
    logger.info("=" * 50)
    
    # Start Prometheus metrics server in background thread
    metrics_thread = threading.Thread(target=start_metrics_server, daemon=True)
    metrics_thread.start()
    
    logger.info("Starting Bytewax processing pipeline...")
    run_main(flow)
