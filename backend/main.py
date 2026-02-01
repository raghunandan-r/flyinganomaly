"""
FastAPI backend - Realtime Hub for SkySentinel.

Serves:
- WebSocket endpoint for real-time flight updates
- REST API for current flight state
- Prometheus metrics endpoint
"""

import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from consumer import FlightCache, FlightConsumer
from anomaly_consumer import AnomalyConsumer
from websocket import ConnectionManager
from models import FlightState
from metrics import get_metrics, HTTP_REQUESTS
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))


# Global state
cache: FlightCache = None
consumer: FlightConsumer = None
anomaly_consumer: AnomalyConsumer = None
connection_manager: ConnectionManager = None
_event_loop: asyncio.AbstractEventLoop = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global cache, consumer, anomaly_consumer, connection_manager, _event_loop
    
    logger.info("=" * 50)
    logger.info("SkySentinel Backend - Starting")
    logger.info("=" * 50)
    
    # Store event loop reference for thread-safe async calls
    _event_loop = asyncio.get_running_loop()
    
    # Initialize cache
    cache = FlightCache()
    logger.info("FlightCache initialized")
    
    # Initialize consumer
    consumer = FlightConsumer(cache)
    consumer.start()
    logger.info("Kafka consumer started")
    
    # Initialize connection manager
    connection_manager = ConnectionManager(cache)
    connection_manager.start_broadcast()
    logger.info("WebSocket broadcast started")
    
    # Initialize anomaly consumer with callback to broadcast via WebSocket
    def on_anomaly_received(anomaly_payload: dict):
        """Callback when anomaly is received from Kafka."""
        # Schedule async broadcast in event loop (thread-safe)
        if _event_loop and _event_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                connection_manager.broadcast_anomaly(anomaly_payload),
                _event_loop
            )
    
    anomaly_consumer = AnomalyConsumer(on_anomaly_received)
    anomaly_consumer.start()
    logger.info("Anomaly consumer started")
    
    yield
    
    # Cleanup
    logger.info("Shutting down...")
    if consumer:
        consumer.stop()
    if anomaly_consumer:
        anomaly_consumer.stop()
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="SkySentinel Backend API",
    description="Realtime hub for flight tracking",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Middleware to track HTTP requests."""
    response = await call_next(request)
    HTTP_REQUESTS.labels(
        method=request.method,
        path=request.url.path,
        status=response.status_code
    ).inc()
    return response


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "SkySentinel Backend",
        "version": "1.0.0",
        "endpoints": {
            "websocket": "/ws/flights",
            "flights": "/flights",
            "health": "/health",
            "metrics": "/metrics"
        }
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "cache_size": cache.size() if cache else 0,
        "connections": len(connection_manager.active_connections) if connection_manager else 0
    }


@app.get("/flights")
async def get_flights():
    """
    Get current flight state snapshot.
    
    Returns JSON array of all current flights.
    """
    if not cache:
        return JSONResponse(
            status_code=503,
            content={"error": "Service not ready"}
        )
    
    flights_dict = cache.get_all()
    flights = [
        {
            "icao24": flight.icao24,
            "callsign": flight.callsign,
            "position": {
                "lat": flight.position.lat,
                "lon": flight.position.lon
            },
            "altitude_m": flight.altitude_m,
            "heading_deg": flight.heading_deg,
            "velocity_mps": flight.velocity_mps,
            "vertical_rate_mps": flight.vertical_rate_mps,
            "on_ground": flight.on_ground,
            "last_contact_unix": flight.last_contact_unix
        }
        for flight in flights_dict.values()
    ]
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "count": len(flights),
        "flights": flights
    }


@app.websocket("/ws/flights")
async def websocket_flights(websocket: WebSocket):
    """
    WebSocket endpoint for real-time flight updates.
    
    Protocol:
    - On connect: sends snapshot message with all current flights
    - Continuously: sends delta updates (upserts + removals) at 2-5Hz
    
    Message formats:
    - Snapshot: {"type": "snapshot", "timestamp": "...", "sequence": 0, "flights": [...]}
    - Delta: {"type": "delta", "timestamp": "...", "sequence": N, "upserts": [...], "removed": [...]}
    """
    if not connection_manager:
        await websocket.close(code=1013, reason="Service not ready")
        return
    
    await connection_manager.handle_client(websocket)


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return await get_metrics()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        log_level="info"
    )
