"""
Airport geofencing for context-aware anomaly detection.
"""

import json
import os
from shapely.geometry import Point, shape
from shapely.strtree import STRtree
from typing import Optional, Tuple

# Default path - will be mounted at /app/static in container
AIRPORTS_FILE = os.getenv("AIRPORTS_FILE", "/app/static/airports.geojson")
AIRPORT_BUFFER_KM = float(os.getenv("AIRPORT_BUFFER_KM", "10.0"))


class AirportGeofence:
    """Fast airport proximity lookup using spatial index."""
    
    def __init__(self, geojson_path: str = AIRPORTS_FILE, buffer_km: float = AIRPORT_BUFFER_KM):
        self.airports = []
        geometries = []
        
        with open(geojson_path) as f:
            data = json.load(f)
        
        for feature in data["features"]:
            geom = shape(feature["geometry"])
            
            # Buffer point airports
            if geom.geom_type == "Point":
                # ~0.009 degrees per km at NYC latitude
                geom = geom.buffer(buffer_km * 0.009)
            
            self.airports.append({
                "code": feature["properties"]["code"],
                "name": feature["properties"]["name"],
                "type": feature["properties"].get("type", "major"),
                "geometry": geom
            })
            geometries.append(geom)
        
        self.tree = STRtree(geometries)
    
    def get_nearby_airport(self, lat: float, lon: float) -> Tuple[bool, Optional[str]]:
        """Check if point is near any airport. Returns (is_near, airport_code)."""
        point = Point(lon, lat)
        
        for i in self.tree.query(point):
            if self.airports[i]["geometry"].contains(point):
                return True, self.airports[i]["code"]
        
        return False, None
    
    def get_flight_phase(
        self, 
        lat: float, 
        lon: float, 
        altitude_m: Optional[float],
        vertical_rate_mps: Optional[float],
        on_ground: bool
    ) -> str:
        """Determine flight phase based on position and state."""
        if on_ground:
            return "GROUND"
        
        if altitude_m is None:
            return "UNKNOWN"
        
        near_airport, _ = self.get_nearby_airport(lat, lon)
        vrate = vertical_rate_mps or 0
        
        if near_airport:
            if altitude_m < 300:  # ~1000ft
                return "LANDING" if vrate < -1 else "TAKEOFF" if vrate > 1 else "GROUND"
            elif altitude_m < 1000:  # ~3000ft
                return "APPROACH" if vrate < 0 else "DEPARTURE"
            elif altitude_m < 3000:  # ~10000ft
                return "APPROACH" if vrate < -2 else "DEPARTURE" if vrate > 2 else "EN_ROUTE"
        
        return "EN_ROUTE"


# Singleton instance
_geofence: Optional[AirportGeofence] = None

def get_geofence() -> AirportGeofence:
    global _geofence
    if _geofence is None:
        _geofence = AirportGeofence()
    return _geofence
