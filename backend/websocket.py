"""
WebSocket handler for flight updates.
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Set, Dict
from pathlib import Path

# Add parent directory to path for contracts import
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import WebSocket, WebSocketDisconnect
from models import FlightState, SnapshotMessage, DeltaMessage, AnomalyMessage
from consumer import FlightCache
from metrics import WEBSOCKET_CONNECTIONS, WEBSOCKET_MESSAGES_SENT
from contracts.validation import (
    validate_snapshot_message,
    validate_delta_message,
    validate_anomaly_message,
)

logger = logging.getLogger(__name__)

WS_DELTA_INTERVAL_MS = int(os.getenv("WS_DELTA_INTERVAL_MS", "200"))
WS_STALE_THRESHOLD_SECONDS = int(os.getenv("WS_STALE_THRESHOLD_SECONDS", "60"))


class ConnectionManager:
    """Manages WebSocket connections and broadcasts."""
    
    def __init__(self, cache: FlightCache):
        self.cache = cache
        self.active_connections: Set[WebSocket] = set()
        self._broadcast_task = None
        self._last_snapshot: Dict[str, FlightState] = {}
    
    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        WEBSOCKET_CONNECTIONS.set(len(self.active_connections))
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
        
        # Send initial snapshot
        await self._send_snapshot(websocket)
    
    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection."""
        self.active_connections.discard(websocket)
        WEBSOCKET_CONNECTIONS.set(len(self.active_connections))
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    def _flight_payload_to_state(self, flight) -> FlightState:
        """Convert FlightPayload to FlightState for WebSocket."""
        current_time = int(datetime.now(timezone.utc).timestamp())
        last_contact = flight.last_contact_unix
        
        # Determine status based on freshness
        age_seconds = current_time - last_contact
        if age_seconds > WS_STALE_THRESHOLD_SECONDS:
            status = "STALE"
        else:
            status = "NORMAL"
        
        return FlightState(
            icao24=flight.icao24,
            callsign=flight.callsign,
            position=flight.position,
            altitude_m=flight.altitude_m,
            heading_deg=flight.heading_deg,
            velocity_mps=flight.velocity_mps,
            vertical_rate_mps=flight.vertical_rate_mps,
            on_ground=flight.on_ground,
            status=status
        )
    
    async def _send_snapshot(self, websocket: WebSocket):
        """Send snapshot message to client."""
        flights_dict = self.cache.get_all()
        flights = [
            self._flight_payload_to_state(flight)
            for flight in flights_dict.values()
        ]
        
        snapshot = SnapshotMessage(
            timestamp=datetime.now(timezone.utc).isoformat(),
            sequence=self.cache.get_sequence(),
            flights=flights
        )
        
        try:
            snapshot_dict = snapshot.model_dump()
            # Validate before sending
            is_valid, validated_snapshot, error = validate_snapshot_message(snapshot_dict)
            if not is_valid:
                logger.error(f"Invalid snapshot message: {error}")
                self.disconnect(websocket)
                return
            await websocket.send_json(snapshot_dict)
            WEBSOCKET_MESSAGES_SENT.labels(type="snapshot").inc()
            logger.debug(f"Sent snapshot with {len(flights)} flights")
        except Exception as e:
            logger.error(f"Failed to send snapshot: {e}")
            self.disconnect(websocket)
    
    async def _compute_delta(self) -> DeltaMessage:
        """Compute delta update from cache."""
        current_time = int(datetime.now(timezone.utc).timestamp())
        flights_dict = self.cache.get_all()
        
        # Convert to FlightState
        current_states: Dict[str, FlightState] = {
            icao24: self._flight_payload_to_state(flight)
            for icao24, flight in flights_dict.items()
        }
        
        # Find upserts (new or changed flights)
        upserts = []
        for icao24, state in current_states.items():
            if icao24 not in self._last_snapshot:
                # New flight
                upserts.append(state)
            else:
                # Check if changed (simple comparison)
                old_state = self._last_snapshot[icao24]
                if (state.position.lat != old_state.position.lat or
                    state.position.lon != old_state.position.lon or
                    state.altitude_m != old_state.altitude_m or
                    state.heading_deg != old_state.heading_deg or
                    state.velocity_mps != old_state.velocity_mps or
                    state.status != old_state.status):
                    upserts.append(state)
        
        # Find removed flights
        removed = [
            icao24 for icao24 in self._last_snapshot
            if icao24 not in current_states
        ]
        
        # Update last snapshot
        self._last_snapshot = current_states.copy()
        
        # Remove stale flights from cache
        removed_stale = self.cache.remove_stale(current_time)
        removed.extend(removed_stale)
        
        return DeltaMessage(
            timestamp=datetime.now(timezone.utc).isoformat(),
            sequence=self.cache.get_sequence(),
            upserts=upserts,
            removed=list(set(removed))  # Deduplicate
        )
    
    async def _broadcast_loop(self):
        """Background task to broadcast delta updates."""
        logger.info(f"Starting broadcast loop (interval: {WS_DELTA_INTERVAL_MS}ms)")
        
        while True:
            try:
                await asyncio.sleep(WS_DELTA_INTERVAL_MS / 1000.0)
                
                if not self.active_connections:
                    continue
                
                # Compute delta
                delta = await self._compute_delta()
                
                # Skip if no changes
                if not delta.upserts and not delta.removed:
                    continue
                
                # Validate and broadcast to all connections
                delta_dict = delta.model_dump()
                is_valid, validated_delta, error = validate_delta_message(delta_dict)
                if not is_valid:
                    logger.error(f"Invalid delta message: {error}")
                    continue
                
                disconnected = []
                
                for connection in self.active_connections:
                    try:
                        await connection.send_json(delta_dict)
                        WEBSOCKET_MESSAGES_SENT.labels(type="delta").inc()
                    except Exception as e:
                        logger.warning(f"Failed to send delta to connection: {e}")
                        disconnected.append(connection)
                
                # Clean up disconnected clients
                for connection in disconnected:
                    self.disconnect(connection)
                
                if delta.upserts or delta.removed:
                    logger.debug(
                        f"Broadcast delta: {len(delta.upserts)} upserts, "
                        f"{len(delta.removed)} removed"
                    )
            
            except Exception as e:
                logger.error(f"Error in broadcast loop: {e}")
    
    def start_broadcast(self):
        """Start broadcast loop."""
        if self._broadcast_task is None or self._broadcast_task.done():
            loop = asyncio.get_event_loop()
            self._broadcast_task = loop.create_task(self._broadcast_loop())
            logger.info("Broadcast loop started")
    
    async def broadcast_anomaly(self, anomaly_payload: dict):
        """
        Broadcast anomaly event to all connected clients.
        
        Args:
            anomaly_payload: Anomaly payload dict from Kafka message
        """
        if not self.active_connections:
            return
        
        # Convert anomaly payload to AnomalyMessage format expected by frontend
        anomaly_msg = AnomalyMessage(
            type="anomaly",
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload={
                "icao24": anomaly_payload.get("icao24"),
                "callsign": anomaly_payload.get("callsign"),
                "anomaly_type": anomaly_payload.get("anomaly_type"),
                "severity": anomaly_payload.get("severity"),
                "position": anomaly_payload.get("position", {}),
                "details": anomaly_payload.get("details", {})
            }
        )
        
        message_json = anomaly_msg.model_dump()
        disconnected = []
        
        for connection in self.active_connections:
            try:
                await connection.send_json(message_json)
                WEBSOCKET_MESSAGES_SENT.labels(type="anomaly").inc()
            except Exception as e:
                logger.warning(f"Failed to send anomaly to connection: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)
        
        logger.debug(f"Broadcast anomaly for {anomaly_payload.get('icao24')}")
    
    async def handle_client(self, websocket: WebSocket):
        """Handle a WebSocket client connection."""
        await self.connect(websocket)
        
        try:
            # Keep connection alive - server pushes updates via broadcast loop
            # Just wait for disconnect
            while True:
                try:
                    # Wait for disconnect or any message
                    await websocket.receive_text()
                except WebSocketDisconnect:
                    break
        
        except WebSocketDisconnect:
            logger.info("Client disconnected")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            self.disconnect(websocket)
