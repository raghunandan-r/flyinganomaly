"""
PostgreSQL database writer for flight history and anomalies.
"""

import os
import logging
from datetime import datetime, timezone
from typing import List, Optional
import psycopg
from psycopg.types.json import Jsonb

from anomaly_detector import Anomaly

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://skysentinel:skysentinel@postgres:5432/skysentinel")

# Connection pool (will be initialized in init_db)
_db_pool: Optional[psycopg.Connection] = None


def init_db():
    """Initialize database connection."""
    global _db_pool
    if _db_pool is None:
        _db_pool = psycopg.connect(DATABASE_URL)
        logger.info("Database connection established")
    return _db_pool


def write_to_db(flight: dict, anomalies: List[Anomaly]):
    """
    Write flight data to PostgreSQL.
    
    Writes to:
    - flights_current (upsert)
    - flights_history (insert)
    - anomalies (insert if any)
    """
    conn = init_db()
    
    try:
        with conn.cursor() as cur:
            # Extract position
            pos = flight.get("position", {})
            lat = pos.get("lat")
            lon = pos.get("lon")
            
            if lat is None or lon is None:
                logger.warning(f"Flight {flight.get('icao24')} missing position, skipping DB write")
                return
            
            # Convert last_contact_unix to timestamp
            last_contact_unix = flight.get("last_contact_unix")
            last_seen = datetime.fromtimestamp(last_contact_unix, tz=timezone.utc) if last_contact_unix else datetime.now(timezone.utc)
            
            # Upsert flights_current
            cur.execute("""
                INSERT INTO flights_current (
                    icao24, callsign, position, altitude_m, altitude_m_smoothed,
                    geo_altitude_m, heading_deg, velocity_mps,
                    vertical_rate_mps, vertical_rate_mps_smoothed,
                    on_ground, squawk, status, flight_phase, near_airport,
                    last_contact_unix, last_seen
                ) VALUES (
                    %s, %s, ST_MakePoint(%s, %s)::geography, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (icao24) DO UPDATE SET
                    callsign = EXCLUDED.callsign,
                    position = EXCLUDED.position,
                    altitude_m = EXCLUDED.altitude_m,
                    altitude_m_smoothed = EXCLUDED.altitude_m_smoothed,
                    geo_altitude_m = EXCLUDED.geo_altitude_m,
                    heading_deg = EXCLUDED.heading_deg,
                    velocity_mps = EXCLUDED.velocity_mps,
                    vertical_rate_mps = EXCLUDED.vertical_rate_mps,
                    vertical_rate_mps_smoothed = EXCLUDED.vertical_rate_mps_smoothed,
                    on_ground = EXCLUDED.on_ground,
                    squawk = EXCLUDED.squawk,
                    status = EXCLUDED.status,
                    flight_phase = EXCLUDED.flight_phase,
                    near_airport = EXCLUDED.near_airport,
                    last_contact_unix = EXCLUDED.last_contact_unix,
                    last_seen = EXCLUDED.last_seen,
                    updated_at = NOW()
            """, (
                flight.get("icao24"),
                flight.get("callsign"),
                lon, lat,
                flight.get("altitude_m"),
                flight.get("altitude_m_smoothed"),
                flight.get("geo_altitude_m"),
                flight.get("heading_deg"),
                flight.get("velocity_mps"),
                flight.get("vertical_rate_mps"),
                flight.get("vertical_rate_mps_smoothed"),
                flight.get("on_ground", False),
                flight.get("squawk"),
                flight.get("status", "NORMAL"),
                flight.get("flight_phase", "UNKNOWN"),
                flight.get("near_airport"),
                last_contact_unix,
                last_seen
            ))
            
            # Insert into flights_history
            cur.execute("""
                INSERT INTO flights_history (
                    icao24, callsign, position, altitude_m, altitude_m_smoothed,
                    heading_deg, velocity_mps, vertical_rate_mps,
                    on_ground, flight_phase, recorded_at
                ) VALUES (
                    %s, %s, ST_MakePoint(%s, %s)::geography, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
            """, (
                flight.get("icao24"),
                flight.get("callsign"),
                lon, lat,
                flight.get("altitude_m"),
                flight.get("altitude_m_smoothed"),
                flight.get("heading_deg"),
                flight.get("velocity_mps"),
                flight.get("vertical_rate_mps"),
                flight.get("on_ground", False),
                flight.get("flight_phase", "UNKNOWN"),
                last_seen
            ))
            
            # Insert anomalies
            for anomaly in anomalies:
                anomaly_pos = anomaly.position
                anomaly_lat = anomaly_pos.get("lat") if anomaly_pos else None
                anomaly_lon = anomaly_pos.get("lon") if anomaly_pos else None
                
                cur.execute("""
                    INSERT INTO anomalies (
                        icao24, callsign, anomaly_type, severity, details,
                        position, altitude_m, near_airport, detected_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        CASE WHEN %s IS NOT NULL AND %s IS NOT NULL 
                             THEN ST_MakePoint(%s, %s)::geography 
                             ELSE NULL END,
                        %s, %s, %s
                    )
                """, (
                    anomaly.icao24,
                    anomaly.callsign,
                    anomaly.anomaly_type.value,
                    anomaly.severity.value,
                    Jsonb(anomaly.details),
                    anomaly_lon, anomaly_lat, anomaly_lon, anomaly_lat,
                    anomaly.altitude_m,
                    anomaly.near_airport,
                    anomaly.detected_at
                ))
            
            conn.commit()
            
    except Exception as e:
        logger.error(f"Error writing to database: {e}", exc_info=True)
        conn.rollback()
        raise
