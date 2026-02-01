"""
SkySentinel Contracts Package

Provides shared constants and validation for message contracts.
"""

from contracts.constants import *
from contracts.validation import (
    FlightPayload,
    FlightStateEnvelope,
    FlightUpdateEnvelope,
    AnomalyPayload,
    AnomalyEventEnvelope,
    FlightState,
    SnapshotMessage,
    DeltaMessage,
    AnomalyMessage,
    validate_flight_state_envelope,
    validate_flight_update_envelope,
    validate_anomaly_event_envelope,
    validate_snapshot_message,
    validate_delta_message,
    validate_anomaly_message,
)

__all__ = [
    # Constants
    "SCHEMA_VERSION",
    "KAFKA_TOPIC_STATE",
    "KAFKA_TOPIC_UPDATES",
    "KAFKA_TOPIC_ANOMALIES",
    "MESSAGE_TYPE_FLIGHT_STATE",
    "MESSAGE_TYPE_FLIGHT_UPDATE",
    "MESSAGE_TYPE_ANOMALY_EVENT",
    "WS_MESSAGE_TYPE_SNAPSHOT",
    "WS_MESSAGE_TYPE_DELTA",
    "WS_MESSAGE_TYPE_ANOMALY",
    # Models
    "FlightPayload",
    "FlightStateEnvelope",
    "FlightUpdateEnvelope",
    "AnomalyPayload",
    "AnomalyEventEnvelope",
    "FlightState",
    "SnapshotMessage",
    "DeltaMessage",
    "AnomalyMessage",
    # Validators
    "validate_flight_state_envelope",
    "validate_flight_update_envelope",
    "validate_anomaly_event_envelope",
    "validate_snapshot_message",
    "validate_delta_message",
    "validate_anomaly_message",
]
