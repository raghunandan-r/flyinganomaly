"""
Kalman filtering for noisy ADS-B data.

Smooths altitude and vertical rate to reduce false anomaly triggers.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class KalmanFilter:
    """1D Kalman filter for a single measurement dimension."""
    
    value: float
    estimate_error: float = 10.0
    process_noise: float = 0.1
    measurement_noise: float = 10.0
    
    def update(self, measurement: float) -> float:
        """Process measurement, return smoothed value."""
        # Prediction (assume constant)
        predicted_error = self.estimate_error + self.process_noise
        
        # Update
        kalman_gain = predicted_error / (predicted_error + self.measurement_noise)
        self.value = self.value + kalman_gain * (measurement - self.value)
        self.estimate_error = (1 - kalman_gain) * predicted_error
        
        return self.value
    
    def reset(self, value: float):
        """Reset filter state."""
        self.value = value
        self.estimate_error = self.measurement_noise


@dataclass
class FlightSmoother:
    """Per-flight smoothing state."""
    
    icao24: str
    altitude_filter: Optional[KalmanFilter] = None
    vrate_filter: Optional[KalmanFilter] = None
    last_contact: Optional[int] = None
    
    def process(self, flight: dict) -> dict:
        """Apply smoothing. Adds *_smoothed fields."""
        contact = flight.get("last_contact_unix", 0)
        
        # Reset filters on large time gap (>2 min = likely different flight or data gap)
        if self.last_contact and contact - self.last_contact > 120:
            self.altitude_filter = None
            self.vrate_filter = None
        self.last_contact = contact
        
        # Smooth altitude
        altitude = flight.get("altitude_m")
        if altitude is not None:
            if self.altitude_filter is None:
                self.altitude_filter = KalmanFilter(
                    value=altitude,
                    process_noise=1.0,
                    measurement_noise=30.0  # ~100ft noise
                )
            flight["altitude_m_smoothed"] = self.altitude_filter.update(altitude)
        
        # Smooth vertical rate
        vrate = flight.get("vertical_rate_mps")
        if vrate is not None:
            if self.vrate_filter is None:
                self.vrate_filter = KalmanFilter(
                    value=vrate,
                    process_noise=0.5,
                    measurement_noise=2.0
                )
            flight["vertical_rate_mps_smoothed"] = self.vrate_filter.update(vrate)
        
        return flight
