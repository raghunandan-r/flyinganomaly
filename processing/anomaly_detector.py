"""
Anomaly detection rules.

Stateful detectors that maintain per-flight history.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from enum import Enum

from geofence import get_geofence


class AnomalyType(str, Enum):
    EMERGENCY_DESCENT = "EMERGENCY_DESCENT"
    GO_AROUND = "GO_AROUND"
    HOLDING = "HOLDING"
    LOW_ALTITUDE_WARNING = "LOW_ALTITUDE_WARNING"
    SQUAWK_EMERGENCY = "SQUAWK_EMERGENCY"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class Anomaly:
    icao24: str
    callsign: Optional[str]
    anomaly_type: AnomalyType
    severity: Severity
    position: dict
    altitude_m: Optional[float]
    near_airport: Optional[str]
    details: dict
    detected_at: datetime


@dataclass
class FlightState:
    """Per-flight state for anomaly detection."""
    icao24: str
    
    # History buffers
    altitude_history: List[Tuple[datetime, float]] = field(default_factory=list)
    position_history: List[Tuple[datetime, float, float]] = field(default_factory=list)
    vrate_history: List[Tuple[datetime, float]] = field(default_factory=list)
    
    # State machine for Go-Around detection
    approach_started: Optional[datetime] = None
    approach_altitude: Optional[float] = None
    
    # Holding detection
    holding_start: Optional[datetime] = None
    
    MAX_HISTORY = 30  # 5 minutes at 10s intervals


class AnomalyDetector:
    """Stateful anomaly detector for a single flight."""
    
    # Thresholds
    EMERGENCY_DESCENT_THRESHOLD_MPS = 15.24  # 3000 ft/min
    GO_AROUND_CLIMB_THRESHOLD_MPS = 7.62     # 1500 ft/min
    HOLDING_VELOCITY_THRESHOLD_MPS = 100.0
    HOLDING_ALTITUDE_THRESHOLD_M = 3000.0
    HOLDING_POSITION_THRESHOLD_M = 10000.0
    HOLDING_DURATION = timedelta(minutes=5)
    LOW_ALTITUDE_THRESHOLD_M = 300.0  # ~1000ft
    
    def __init__(self):
        self.state: Optional[FlightState] = None
        self.geofence = get_geofence()
    
    def process(self, flight: dict) -> Tuple[dict, List[Anomaly]]:
        """
        Process flight update, detect anomalies. 
        
        Returns:
            (enriched_flight, list_of_anomalies)
        """
        icao24 = flight["icao24"]
        anomalies = []
        
        # Initialize state
        if self.state is None or self.state.icao24 != icao24:
            self.state = FlightState(icao24=icao24)
        
        now = datetime.utcnow()
        pos = flight.get("position", {})
        lat, lon = pos.get("lat"), pos.get("lon")
        
        # Use smoothed values if available
        altitude = flight.get("altitude_m_smoothed") or flight.get("altitude_m")
        vrate = flight.get("vertical_rate_mps_smoothed") or flight.get("vertical_rate_mps")
        
        # Update history
        if altitude is not None:
            self.state.altitude_history.append((now, altitude))
            self.state.altitude_history = self.state.altitude_history[-FlightState.MAX_HISTORY:]
        
        if vrate is not None:
            self.state.vrate_history.append((now, vrate))
            self.state.vrate_history = self.state.vrate_history[-FlightState.MAX_HISTORY:]
        
        if lat is not None and lon is not None:
            self.state.position_history.append((now, lat, lon))
            self.state.position_history = self.state.position_history[-FlightState.MAX_HISTORY:]
        
        # Get airport context
        near_airport, airport_code = self.geofence.get_nearby_airport(lat, lon) if lat and lon else (False, None)
        flight["near_airport"] = airport_code
        flight["flight_phase"] = self.geofence.get_flight_phase(
            lat, lon, altitude, vrate, flight.get("on_ground", False)
        ) if lat and lon else "UNKNOWN"
        
        # Check for squawk emergency codes
        squawk = flight.get("squawk")
        if squawk in ("7700", "7600", "7500"):
            anomalies.append(self._create_anomaly(
                flight, AnomalyType.SQUAWK_EMERGENCY, Severity.HIGH,
                {"squawk": squawk, "meaning": {
                    "7700": "General Emergency",
                    "7600": "Radio Failure", 
                    "7500": "Hijack"
                }.get(squawk)}
            ))
        
        # Rule 1: Emergency Descent
        descent_anomaly = self._check_emergency_descent(flight, vrate, near_airport)
        if descent_anomaly:
            anomalies.append(descent_anomaly)
            flight["status"] = AnomalyType.EMERGENCY_DESCENT.value
        
        # Rule 2: Go-Around
        go_around_anomaly = self._check_go_around(flight, altitude, vrate, near_airport)
        if go_around_anomaly:
            anomalies.append(go_around_anomaly)
            flight["status"] = AnomalyType.GO_AROUND.value
        
        # Rule 3: Low Altitude Warning (away from airports)
        low_alt_anomaly = self._check_low_altitude(flight, altitude, near_airport)
        if low_alt_anomaly:
            anomalies.append(low_alt_anomaly)
            flight["status"] = AnomalyType.LOW_ALTITUDE_WARNING.value
        
        # Rule 4: Holding Pattern
        holding_anomaly = self._check_holding(flight, altitude, vrate)
        if holding_anomaly:
            anomalies.append(holding_anomaly)
            flight["status"] = AnomalyType.HOLDING.value
        
        # Default status
        if "status" not in flight:
            flight["status"] = "NORMAL"
        
        return flight, anomalies
    
    def _check_emergency_descent(
        self, flight: dict, vrate: Optional[float], near_airport: bool
    ) -> Optional[Anomaly]:
        """Detect rapid descent (>3000 ft/min)."""
        if vrate is None or vrate >= -self.EMERGENCY_DESCENT_THRESHOLD_MPS:
            return None
        
        # Ignore if near airport (could be normal landing)
        if near_airport and flight.get("altitude_m", 10000) < 3000:
            return None
        
        # Confirm with history (3 consecutive descending readings)
        if len(self.state.vrate_history) < 3:
            return None
        
        recent = [v for _, v in self.state.vrate_history[-3:]]
        if not all(v < -self.EMERGENCY_DESCENT_THRESHOLD_MPS * 0.8 for v in recent):
            return None
        
        return self._create_anomaly(
            flight, AnomalyType.EMERGENCY_DESCENT, Severity.HIGH,
            {
                "descent_rate_mps": vrate,
                "descent_rate_fpm": vrate * 196.85,
                "confirmed_samples": 3
            }
        )
    
    def _check_go_around(
        self, flight: dict, altitude: Optional[float], vrate: Optional[float], near_airport: bool
    ) -> Optional[Anomaly]:
        """
        Detect go-around: approach abort near airport.
        
        Pattern:
        1. State A: Altitude < 600m (2000ft), near airport, descending
        2. State B: Sudden climb > 1500 ft/min
        3. Transition A→B within 30 seconds
        """
        if altitude is None or vrate is None:
            return None
        
        now = datetime.utcnow()
        
        # Check for approach state
        if near_airport and altitude < 600 and vrate < -2:
            if self.state.approach_started is None:
                self.state.approach_started = now
                self.state.approach_altitude = altitude
        
        # Check for abort (sudden climb while in approach state)
        if self.state.approach_started:
            time_in_approach = now - self.state.approach_started
            
            if vrate > self.GO_AROUND_CLIMB_THRESHOLD_MPS and time_in_approach < timedelta(seconds=60):
                # Detected go-around!
                anomaly = self._create_anomaly(
                    flight, AnomalyType.GO_AROUND, Severity.MEDIUM,
                    {
                        "approach_duration_s": time_in_approach.total_seconds(),
                        "lowest_altitude_m": self.state.approach_altitude,
                        "climb_rate_mps": vrate,
                        "climb_rate_fpm": vrate * 196.85
                    }
                )
                
                # Reset state
                self.state.approach_started = None
                self.state.approach_altitude = None
                
                return anomaly
            
            # Approach timed out or landed
            if time_in_approach > timedelta(seconds=120) or flight.get("on_ground"):
                self.state.approach_started = None
                self.state.approach_altitude = None
        
        return None
    
    def _check_low_altitude(
        self, flight: dict, altitude: Optional[float], near_airport: bool
    ) -> Optional[Anomaly]:
        """Detect dangerously low altitude away from airports."""
        if altitude is None or near_airport or flight.get("on_ground"):
            return None
        
        if altitude < self.LOW_ALTITUDE_THRESHOLD_M:
            return self._create_anomaly(
                flight, AnomalyType.LOW_ALTITUDE_WARNING, Severity.HIGH,
                {
                    "altitude_m": altitude,
                    "altitude_ft": altitude * 3.28084,
                    "threshold_ft": self.LOW_ALTITUDE_THRESHOLD_M * 3.28084
                }
            )
        
        return None
    
    def _check_holding(
        self, flight: dict, altitude: Optional[float], vrate: Optional[float]
    ) -> Optional[Anomaly]:
        """Detect holding pattern (slow, high altitude, same area)."""
        velocity = flight.get("velocity_mps")
        
        if altitude is None or velocity is None:
            return None
        
        # Must be high and slow
        if altitude < self.HOLDING_ALTITUDE_THRESHOLD_M or velocity > self.HOLDING_VELOCITY_THRESHOLD_MPS:
            self.state.holding_start = None
            return None
        
        if len(self.state.position_history) < 2:
            return None
        
        now = datetime.utcnow()
        oldest_time, oldest_lat, oldest_lon = self.state.position_history[0]
        
        if now - oldest_time < self.HOLDING_DURATION:
            return None
        
        # Check if still in same general area
        pos = flight.get("position", {})
        lat, lon = pos.get("lat"), pos.get("lon")
        
        if lat is None or lon is None:
            return None
        
        distance = self._haversine(oldest_lat, oldest_lon, lat, lon)
        
        if distance < self.HOLDING_POSITION_THRESHOLD_M:
            if self.state.holding_start is None:
                self.state.holding_start = oldest_time
            
            return self._create_anomaly(
                flight, AnomalyType.HOLDING, Severity.LOW,
                {
                    "hold_duration_minutes": (now - self.state.holding_start).total_seconds() / 60,
                    "hold_center_lat": oldest_lat,
                    "hold_center_lon": oldest_lon,
                    "distance_from_start_m": distance
                }
            )
        
        self.state.holding_start = None
        return None
    
    def _create_anomaly(
        self, flight: dict, anomaly_type: AnomalyType, severity: Severity, details: dict
    ) -> Anomaly:
        """Create anomaly record."""
        pos = flight.get("position", {})
        return Anomaly(
            icao24=flight["icao24"],
            callsign=flight.get("callsign"),
            anomaly_type=anomaly_type,
            severity=severity,
            position=pos,
            altitude_m=flight.get("altitude_m"),
            near_airport=flight.get("near_airport"),
            details=details,
            detected_at=datetime.utcnow()
        )
    
    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance in meters between two points."""
        import math
        R = 6371000  # Earth radius in meters
        
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))
