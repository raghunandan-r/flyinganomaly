/**
 * FlightTooltip component for displaying flight details on hover
 */

import type { Flight } from '../types/flight';

interface FlightTooltipProps {
  flight: Flight | null;
  position: { x: number; y: number } | null;
}

export function FlightTooltip({ flight, position }: FlightTooltipProps) {
  if (!flight || !position) return null;

  const formatAltitude = (alt: number | null) => {
    if (alt === null) return 'N/A';
    return `${Math.round(alt)}m (${Math.round(alt * 3.28084)}ft)`;
  };

  const formatSpeed = (speed: number | null) => {
    if (speed === null) return 'N/A';
    return `${Math.round(speed)} m/s (${Math.round(speed * 1.94384)} kts)`;
  };

  const formatHeading = (heading: number | null) => {
    if (heading === null) return 'N/A';
    return `${Math.round(heading)}°`;
  };

  const formatVerticalRate = (vrate: number | null) => {
    if (vrate === null) return 'N/A';
    const fpm = Math.round(vrate * 196.85);
    return `${Math.round(vrate)} m/s (${fpm > 0 ? '+' : ''}${fpm} fpm)`;
  };

  return (
    <div
      style={{
        position: 'fixed',
        left: `${position.x + 10}px`,
        top: `${position.y + 10}px`,
        background: 'rgba(0, 0, 0, 0.9)',
        color: 'white',
        padding: '12px',
        borderRadius: '6px',
        minWidth: '250px',
        zIndex: 2000,
        pointerEvents: 'none',
        border: flight.status === 'ANOMALY' ? '2px solid #F44336' : '1px solid #666',
      }}
    >
      <div style={{ marginBottom: '8px' }}>
        <strong style={{ fontSize: '1.1em' }}>
          {flight.callsign || flight.icao24}
        </strong>
        {flight.status === 'ANOMALY' && (
          <span
            style={{
              marginLeft: '8px',
              color: '#F44336',
              fontSize: '0.9em',
            }}
          >
            ANOMALY
          </span>
        )}
      </div>

      <div style={{ fontSize: '0.9em', lineHeight: '1.6' }}>
        <div>
          <strong>ICAO24:</strong> {flight.icao24}
        </div>
        <div>
          <strong>Position:</strong> {flight.position.lat.toFixed(4)}, {flight.position.lon.toFixed(4)}
        </div>
        <div>
          <strong>Altitude:</strong> {formatAltitude(flight.altitude_m)}
        </div>
        <div>
          <strong>Speed:</strong> {formatSpeed(flight.velocity_mps)}
        </div>
        <div>
          <strong>Heading:</strong> {formatHeading(flight.heading_deg)}
        </div>
        <div>
          <strong>Vertical Rate:</strong> {formatVerticalRate(flight.vertical_rate_mps)}
        </div>
        <div>
          <strong>On Ground:</strong> {flight.on_ground ? 'Yes' : 'No'}
        </div>
        {flight.squawk && (
          <div>
            <strong>Squawk:</strong> {flight.squawk}
          </div>
        )}
      </div>
    </div>
  );
}
