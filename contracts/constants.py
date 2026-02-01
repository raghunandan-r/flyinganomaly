"""
Shared constants for SkySentinel services.

This module provides a single source of truth for:
- Kafka topic names
- Message types
- Schema versions

All services should import from this module to ensure consistency.
"""

# Schema version
SCHEMA_VERSION = 1

# Kafka Topic Names
KAFKA_TOPIC_STATE = "flights.state"
KAFKA_TOPIC_UPDATES = "flights.updates"
KAFKA_TOPIC_ANOMALIES = "flights.anomalies"
KAFKA_TOPIC_HEARTBEAT = "ingestion.heartbeat"
KAFKA_TOPIC_DEADLETTER = "deadletter.flights"

# Message Types
MESSAGE_TYPE_FLIGHT_STATE = "flight_state"
MESSAGE_TYPE_FLIGHT_UPDATE = "flight_update"
MESSAGE_TYPE_ANOMALY_EVENT = "anomaly_event"
MESSAGE_TYPE_HEARTBEAT = "heartbeat"

# WebSocket Message Types
WS_MESSAGE_TYPE_SNAPSHOT = "snapshot"
WS_MESSAGE_TYPE_DELTA = "delta"
WS_MESSAGE_TYPE_ANOMALY = "anomaly"

# Anomaly Types
ANOMALY_TYPE_EMERGENCY_DESCENT = "EMERGENCY_DESCENT"
ANOMALY_TYPE_GO_AROUND = "GO_AROUND"
ANOMALY_TYPE_HOLDING = "HOLDING"
ANOMALY_TYPE_LOW_ALTITUDE_WARNING = "LOW_ALTITUDE_WARNING"
ANOMALY_TYPE_SQUAWK_7700 = "SQUAWK_7700"
ANOMALY_TYPE_SQUAWK_7600 = "SQUAWK_7600"
ANOMALY_TYPE_SQUAWK_7500 = "SQUAWK_7500"
ANOMALY_TYPE_SQUAWK_EMERGENCY = "SQUAWK_EMERGENCY"

# Severity Levels
SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"

# Flight Status
FLIGHT_STATUS_NORMAL = "NORMAL"
FLIGHT_STATUS_STALE = "STALE"
FLIGHT_STATUS_ANOMALY = "ANOMALY"

# Data Providers
PROVIDER_OPENSKY = "opensky"
PROVIDER_SKYSENTINEL_PROCESSING = "skysentinel-processing"

# Ingestion Modes
MODE_LIVE = "live"
MODE_REPLAY = "replay"
