/**
 * Flight data types matching the WebSocket protocol specification
 * See: docs/final_architecture.md Section 8
 */

export interface Position {
  lat: number;
  lon: number;
}

export interface Flight {
  icao24: string;
  callsign: string | null;
  position: Position;
  altitude_m: number | null;
  heading_deg: number | null;
  velocity_mps: number | null;
  vertical_rate_mps: number | null;
  on_ground: boolean;
  status?: 'NORMAL' | 'ANOMALY';
  // Additional fields from payload
  geo_altitude_m?: number | null;
  squawk?: string | null;
  spi?: boolean;
  time_position_unix?: number | null;
  last_contact_unix?: number | null;
}

export interface SnapshotMessage {
  type: 'snapshot';
  timestamp: string;
  sequence: number;
  flights: Flight[];
}

export interface DeltaMessage {
  type: 'delta';
  timestamp: string;
  sequence: number;
  upserts: Flight[];
  removed: string[]; // Array of icao24 strings
}

export interface AnomalyMessage {
  type: 'anomaly';
  timestamp: string;
  payload: {
    icao24: string;
    callsign: string | null;
    anomaly_type: string;
    severity: 'LOW' | 'MEDIUM' | 'HIGH';
    position: Position;
    details: Record<string, unknown>;
  };
}

export type WebSocketMessage = SnapshotMessage | DeltaMessage | AnomalyMessage;

export interface FlightState {
  flights: Map<string, Flight>;
  lastUpdate: Date | null;
  sequence: number;
  connectionStatus: 'disconnected' | 'connecting' | 'connected' | 'error';
  error: string | null;
}

export interface FlightFilters {
  minAltitude: number | null;
  maxAltitude: number | null;
  showGround: boolean;
  callsignSearch: string;
}
