"""
Validation library for SkySentinel message contracts.

Provides Pydantic models matching the JSON schemas for runtime validation.
All services should use these models to validate messages before processing.
"""

from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from contracts.constants import (
    SCHEMA_VERSION,
    MESSAGE_TYPE_FLIGHT_STATE,
    MESSAGE_TYPE_FLIGHT_UPDATE,
    MESSAGE_TYPE_ANOMALY_EVENT,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    SEVERITY_HIGH,
    ANOMALY_TYPE_EMERGENCY_DESCENT,
    ANOMALY_TYPE_GO_AROUND,
    ANOMALY_TYPE_HOLDING,
    ANOMALY_TYPE_LOW_ALTITUDE_WARNING,
    ANOMALY_TYPE_SQUAWK_7700,
    ANOMALY_TYPE_SQUAWK_7600,
    ANOMALY_TYPE_SQUAWK_7500,
    ANOMALY_TYPE_SQUAWK_EMERGENCY,
    PROVIDER_OPENSKY,
    PROVIDER_SKYSENTINEL_PROCESSING,
    MODE_LIVE,
    MODE_REPLAY,
)


# ============================================================================
# Shared Components
# ============================================================================

class Position(BaseModel):
    """Geographic position."""
    lat: float = Field(ge=-90, le=90, description="Latitude in degrees (WGS84)")
    lon: float = Field(ge=-180, le=180, description="Longitude in degrees (WGS84)")


class BoundingBox(BaseModel):
    """Geographic bounding box."""
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float


class SourceInfo(BaseModel):
    """Source information for envelope."""
    provider: Literal["opensky", "skysentinel-processing"]
    mode: Optional[Literal["live", "replay"]] = None
    bbox: Optional[BoundingBox] = None
    poll_interval_s: Optional[int] = Field(None, ge=1)


# ============================================================================
# Flight Payload
# ============================================================================

class FlightPayload(BaseModel):
    """Core flight data payload."""
    icao24: str = Field(pattern=r"^[0-9a-f]{6}$", description="ICAO 24-bit address (hex, lowercase)")
    callsign: Optional[str] = None
    position: Position
    altitude_m: Optional[float] = None
    geo_altitude_m: Optional[float] = None
    velocity_mps: Optional[float] = Field(None, ge=0, description="Ground speed in m/s")
    heading_deg: Optional[float] = Field(None, ge=0, lt=360, description="True track in degrees [0, 360)")
    vertical_rate_mps: Optional[float] = None
    on_ground: bool = False
    squawk: Optional[str] = None
    spi: bool = False
    time_position_unix: Optional[int] = None
    last_contact_unix: int = Field(description="Most recent message timestamp (freshness clock)")

    @field_validator("icao24")
    @classmethod
    def validate_icao24(cls, v: str) -> str:
        """Normalize icao24 to lowercase."""
        return v.lower()


# ============================================================================
# Flight Envelopes (Kafka Topics)
# ============================================================================

class FlightStateEnvelope(BaseModel):
    """Envelope for flights.state topic (compacted)."""
    schema_version: int = Field(default=SCHEMA_VERSION, const=True)
    type: Literal["flight_state"] = Field(default=MESSAGE_TYPE_FLIGHT_STATE, const=True)
    produced_at: datetime
    source: SourceInfo
    payload: FlightPayload

    @field_validator("produced_at", mode="before")
    @classmethod
    def parse_produced_at(cls, v):
        """Parse ISO 8601 datetime string."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class FlightUpdateEnvelope(BaseModel):
    """Envelope for flights.updates topic (append-only)."""
    schema_version: int = Field(default=SCHEMA_VERSION, const=True)
    type: Literal["flight_update"] = Field(default=MESSAGE_TYPE_FLIGHT_UPDATE, const=True)
    produced_at: datetime
    source: SourceInfo
    payload: FlightPayload

    @field_validator("produced_at", mode="before")
    @classmethod
    def parse_produced_at(cls, v):
        """Parse ISO 8601 datetime string."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


# ============================================================================
# Anomaly Payload and Envelope
# ============================================================================

class AnomalyPayload(BaseModel):
    """Anomaly event payload."""
    icao24: str = Field(pattern=r"^[0-9a-f]{6}$")
    callsign: Optional[str] = None
    anomaly_type: Literal[
        "EMERGENCY_DESCENT",
        "GO_AROUND",
        "HOLDING",
        "LOW_ALTITUDE_WARNING",
        "SQUAWK_7700",
        "SQUAWK_7600",
        "SQUAWK_7500",
        "SQUAWK_EMERGENCY"
    ]
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    detected_at: datetime
    position: Position
    details: dict = Field(default_factory=dict, description="Anomaly-specific details")

    @field_validator("icao24")
    @classmethod
    def validate_icao24(cls, v: str) -> str:
        """Normalize icao24 to lowercase."""
        return v.lower()

    @field_validator("detected_at", mode="before")
    @classmethod
    def parse_detected_at(cls, v):
        """Parse ISO 8601 datetime string."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class AnomalyEventEnvelope(BaseModel):
    """Envelope for flights.anomalies topic."""
    schema_version: int = Field(default=SCHEMA_VERSION, const=True)
    type: Literal["anomaly_event"] = Field(default=MESSAGE_TYPE_ANOMALY_EVENT, const=True)
    produced_at: datetime
    source: SourceInfo
    payload: AnomalyPayload

    @field_validator("produced_at", mode="before")
    @classmethod
    def parse_produced_at(cls, v):
        """Parse ISO 8601 datetime string."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


# ============================================================================
# WebSocket Messages
# ============================================================================

class FlightState(BaseModel):
    """Flight state for WebSocket messages."""
    icao24: str = Field(pattern=r"^[0-9a-f]{6}$")
    callsign: Optional[str] = None
    position: Position
    altitude_m: Optional[float] = None
    heading_deg: Optional[float] = Field(None, ge=0, lt=360)
    velocity_mps: Optional[float] = Field(None, ge=0)
    vertical_rate_mps: Optional[float] = None
    on_ground: bool = False
    status: Literal["NORMAL", "STALE", "ANOMALY"] = "NORMAL"


class SnapshotMessage(BaseModel):
    """WebSocket snapshot message (sent on connect)."""
    type: Literal["snapshot"] = "snapshot"
    timestamp: datetime
    sequence: int = Field(ge=0)
    flights: list[FlightState]

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v):
        """Parse ISO 8601 datetime string."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class DeltaMessage(BaseModel):
    """WebSocket delta message (sent periodically)."""
    type: Literal["delta"] = "delta"
    timestamp: datetime
    sequence: int = Field(ge=0)
    upserts: list[FlightState]
    removed: list[str] = Field(description="List of icao24 values")

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v):
        """Parse ISO 8601 datetime string."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v

    @field_validator("removed")
    @classmethod
    def validate_removed(cls, v: list) -> list:
        """Validate removed icao24 values."""
        for icao24 in v:
            if not isinstance(icao24, str) or len(icao24) != 6:
                raise ValueError(f"Invalid icao24 in removed list: {icao24}")
        return v


class AnomalyMessage(BaseModel):
    """WebSocket anomaly message."""
    type: Literal["anomaly"] = "anomaly"
    timestamp: datetime
    payload: AnomalyPayload

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v):
        """Parse ISO 8601 datetime string."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


# ============================================================================
# Validation Functions
# ============================================================================

def validate_flight_state_envelope(data: dict) -> tuple[bool, Optional[FlightStateEnvelope], Optional[str]]:
    """
    Validate FlightStateEnvelope.
    
    Returns:
        (is_valid, envelope_or_none, error_message_or_none)
    """
    try:
        envelope = FlightStateEnvelope(**data)
        return True, envelope, None
    except Exception as e:
        return False, None, str(e)


def validate_flight_update_envelope(data: dict) -> tuple[bool, Optional[FlightUpdateEnvelope], Optional[str]]:
    """
    Validate FlightUpdateEnvelope.
    
    Returns:
        (is_valid, envelope_or_none, error_message_or_none)
    """
    try:
        envelope = FlightUpdateEnvelope(**data)
        return True, envelope, None
    except Exception as e:
        return False, None, str(e)


def validate_anomaly_event_envelope(data: dict) -> tuple[bool, Optional[AnomalyEventEnvelope], Optional[str]]:
    """
    Validate AnomalyEventEnvelope.
    
    Returns:
        (is_valid, envelope_or_none, error_message_or_none)
    """
    try:
        envelope = AnomalyEventEnvelope(**data)
        return True, envelope, None
    except Exception as e:
        return False, None, str(e)


def validate_snapshot_message(data: dict) -> tuple[bool, Optional[SnapshotMessage], Optional[str]]:
    """
    Validate SnapshotMessage.
    
    Returns:
        (is_valid, message_or_none, error_message_or_none)
    """
    try:
        message = SnapshotMessage(**data)
        return True, message, None
    except Exception as e:
        return False, None, str(e)


def validate_delta_message(data: dict) -> tuple[bool, Optional[DeltaMessage], Optional[str]]:
    """
    Validate DeltaMessage.
    
    Returns:
        (is_valid, message_or_none, error_message_or_none)
    """
    try:
        message = DeltaMessage(**data)
        return True, message, None
    except Exception as e:
        return False, None, str(e)


def validate_anomaly_message(data: dict) -> tuple[bool, Optional[AnomalyMessage], Optional[str]]:
    """
    Validate AnomalyMessage.
    
    Returns:
        (is_valid, message_or_none, error_message_or_none)
    """
    try:
        message = AnomalyMessage(**data)
        return True, message, None
    except Exception as e:
        return False, None, str(e)
