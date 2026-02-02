/**
 * FlightGlobe component using Globe.gl for 3D visualization
 */

import { useEffect, useRef } from 'react';
import Globe from 'globe.gl';
import type { Flight } from '../types/flight';
import { createGhostFlight } from '../utils/interpolation';

interface FlightGlobeProps {
  flights: Flight[];
  selectedFlight: Flight | null;
  cockpitView: boolean;
  onFlightClick: (flight: Flight | null) => void;
  onFlightHover?: (flight: Flight | null) => void;
}

export function FlightGlobe({
  flights,
  selectedFlight,
  cockpitView,
  onFlightClick,
  onFlightHover,
}: FlightGlobeProps) {
  const globeEl = useRef<HTMLDivElement>(null);
  const globeRef = useRef<any>(null);

  // Initialize Globe
  useEffect(() => {
    if (!globeEl.current) return;

    // Globe.gl uses factory pattern at runtime but types expect constructor
    const globe = (Globe as any)()(globeEl.current)
      .globeImageUrl('//unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
      .bumpImageUrl('//unpkg.com/three-globe/example/img/earth-topology.png')
      .backgroundImageUrl('//unpkg.com/three-globe/example/img/night-sky.png')
      .showAtmosphere(true)
      .atmosphereColor('#3a228a')
      .atmosphereAltitude(0.15);

    globeRef.current = globe;

    return () => {
      // Cleanup
      if (globeRef.current && globeEl.current) {
        // Remove all event listeners and clear data
        globeRef.current.pointsData([]);
        // Globe.gl will clean up automatically when the DOM element is removed
      }
    };
  }, []);

  // Update flight points
  useEffect(() => {
    if (!globeRef.current) return;

    const now = new Date();
    const points = flights.map((flight) => {
      // Create ghost flight for stale data visualization
      const lastUpdate = flight.last_contact_unix
        ? new Date(flight.last_contact_unix * 1000)
        : now;
      const ghostFlight = createGhostFlight(flight, lastUpdate);

      const position = ghostFlight.age_ms > 30000
        ? ghostFlight.interpolatedPosition
        : flight.position;

      return {
        lat: position.lat,
        lng: position.lon,
        altitude: (flight.altitude_m || 0) / 1000, // Convert to km for globe
        size: flight.on_ground ? 0.3 : 0.5,
        color: flight.status === 'ANOMALY' ? '#ff0000' : '#4CAF50',
        flight,
      };
    });

    globeRef.current.pointsData(points);

    // Handle point clicks
    globeRef.current.onPointClick((point: any) => {
      onFlightClick(point.flight);
    });

    // Handle point hover
    if (onFlightHover) {
      globeRef.current.onPointHover((point: any) => {
        onFlightHover(point?.flight || null);
      });
    }
  }, [flights, onFlightClick]);

  // Cockpit view: lock camera on selected flight
  useEffect(() => {
    if (!globeRef.current || !selectedFlight || !cockpitView) return;

    const { position, heading_deg, altitude_m } = selectedFlight;
    const altitude_km = (altitude_m || 0) / 1000;

    // Set camera to follow flight
    globeRef.current.pointOfView(
      {
        lat: position.lat,
        lng: position.lon,
        altitude: altitude_km + 0.5, // Slightly above the aircraft
      },
      0 // Instant transition
    );

    // Rotate camera to match heading
    if (heading_deg !== null) {
      // Globe.gl uses radians, and heading is 0-360 degrees (0 = North)
      // Note: Globe.gl doesn't directly support camera rotation, but we can
      // use the pointOfView with a slight offset to simulate following
      // const headingRad = ((heading_deg - 90) * Math.PI) / 180;
    }
  }, [selectedFlight, cockpitView]);

  // Reset camera when exiting cockpit view
  useEffect(() => {
    if (!globeRef.current || cockpitView) return;

    globeRef.current.pointOfView(
      {
        lat: 40.7, // NYC center
        lng: -73.9,
        altitude: 2.5,
      },
      1000 // Smooth transition
    );
  }, [cockpitView]);

  return (
    <div
      ref={globeEl}
      style={{
        width: '100%',
        height: '100%',
        position: 'relative',
      }}
    />
  );
}
