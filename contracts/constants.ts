/**
 * Shared constants for SkySentinel frontend.
 * 
 * This module provides a single source of truth for:
 * - WebSocket message types
 * - Flight status values
 * - Anomaly types and severities
 * 
 * Should match contracts/constants.py for consistency.
 */

// Schema version
export const SCHEMA_VERSION = 1;

// WebSocket Message Types
export const WS_MESSAGE_TYPE_SNAPSHOT = "snapshot";
export const WS_MESSAGE_TYPE_DELTA = "delta";
export const WS_MESSAGE_TYPE_ANOMALY = "anomaly";

// Anomaly Types
export const ANOMALY_TYPE_EMERGENCY_DESCENT = "EMERGENCY_DESCENT";
export const ANOMALY_TYPE_GO_AROUND = "GO_AROUND";
export const ANOMALY_TYPE_HOLDING = "HOLDING";
export const ANOMALY_TYPE_LOW_ALTITUDE_WARNING = "LOW_ALTITUDE_WARNING";
export const ANOMALY_TYPE_SQUAWK_7700 = "SQUAWK_7700";
export const ANOMALY_TYPE_SQUAWK_7600 = "SQUAWK_7600";
export const ANOMALY_TYPE_SQUAWK_7500 = "SQUAWK_7500";
export const ANOMALY_TYPE_SQUAWK_EMERGENCY = "SQUAWK_EMERGENCY";

// Severity Levels
export const SEVERITY_LOW = "LOW";
export const SEVERITY_MEDIUM = "MEDIUM";
export const SEVERITY_HIGH = "HIGH";

// Flight Status
export const FLIGHT_STATUS_NORMAL = "NORMAL";
export const FLIGHT_STATUS_STALE = "STALE";
export const FLIGHT_STATUS_ANOMALY = "ANOMALY";

// Type definitions for better type safety
export type AnomalyType =
  | typeof ANOMALY_TYPE_EMERGENCY_DESCENT
  | typeof ANOMALY_TYPE_GO_AROUND
  | typeof ANOMALY_TYPE_HOLDING
  | typeof ANOMALY_TYPE_LOW_ALTITUDE_WARNING
  | typeof ANOMALY_TYPE_SQUAWK_7700
  | typeof ANOMALY_TYPE_SQUAWK_7600
  | typeof ANOMALY_TYPE_SQUAWK_7500
  | typeof ANOMALY_TYPE_SQUAWK_EMERGENCY;

export type Severity =
  | typeof SEVERITY_LOW
  | typeof SEVERITY_MEDIUM
  | typeof SEVERITY_HIGH;

export type FlightStatus =
  | typeof FLIGHT_STATUS_NORMAL
  | typeof FLIGHT_STATUS_STALE
  | typeof FLIGHT_STATUS_ANOMALY;
