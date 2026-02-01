"""
Data models for flight state and WebSocket messages.
"""

from typing import Optional
from pydantic import BaseModel


class Position(BaseModel):
    """Geographic position."""
    lat: float
    lon: float


class FlightPayload(BaseModel):
    """Core flight data payload."""
    icao24: str
    callsign: Optional[str] = None
    position: Position
    altitude_m: Optional[float] = None
    geo_altitude_m: Optional[float] = None
    velocity_mps: Optional[float] = None
    heading_deg: Optional[float] = None
    vertical_rate_mps: Optional[float] = None
    on_ground: bool = False
    squawk: Optional[str] = None
    spi: bool = False
    time_position_unix: Optional[int] = None
    last_contact_unix: int


class FlightState(BaseModel):
    """Flight state with status indicator."""
    icao24: str
    callsign: Optional[str] = None
    position: Position
    altitude_m: Optional[float] = None
    heading_deg: Optional[float] = None
    velocity_mps: Optional[float] = None
    vertical_rate_mps: Optional[float] = None
    on_ground: bool = False
    status: str = "NORMAL"  # NORMAL, STALE, etc.


class SnapshotMessage(BaseModel):
    """WebSocket snapshot message (sent on connect)."""
    type: str = "snapshot"
    timestamp: str
    sequence: int
    flights: list[FlightState]


class DeltaMessage(BaseModel):
    """WebSocket delta message (sent periodically)."""
    type: str = "delta"
    timestamp: str
    sequence: int
    upserts: list[FlightState]
    removed: list[str]  # List of icao24 values


class AnomalyMessage(BaseModel):
    """WebSocket anomaly message (sent when anomaly detected)."""
    type: str = "anomaly"
    timestamp: str
    payload: dict  # Contains icao24, callsign, anomaly_type, severity, position, details
