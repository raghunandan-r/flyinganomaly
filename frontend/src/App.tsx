/**
 * Main App component
 */

import { useState, useRef, useEffect } from 'react';
import { FlightGlobe } from './components/FlightGlobe';
import { FlightFiltersComponent } from './components/FlightFilters';
import { StatusBar } from './components/StatusBar';
import { FlightTooltip } from './components/FlightTooltip';
import { useFlightStream } from './hooks/useFlightStream';
import { useFlightState } from './hooks/useFlightState';
import type { Flight, FlightFilters } from './types/flight';

function App() {
  const {
    flights,
    lastUpdate,
    connectionStatus,
    error,
  } = useFlightStream();

  const [filters, setFilters] = useState<FlightFilters>({
    minAltitude: null,
    maxAltitude: null,
    showGround: true,
    callsignSearch: '',
  });

  const [selectedFlight, setSelectedFlight] = useState<Flight | null>(null);
  const [cockpitView, setCockpitView] = useState(false);
  const [hoveredFlight, setHoveredFlight] = useState<Flight | null>(null);
  const [mousePosition, setMousePosition] = useState<{ x: number; y: number } | null>(null);

  const { filteredFlights, stats } = useFlightState(flights, filters);

  // Track mouse position for tooltip
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      setMousePosition({ x: e.clientX, y: e.clientY });
    };

    window.addEventListener('mousemove', handleMouseMove);
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, []);

  // Update hovered flight based on filtered flights
  useEffect(() => {
    // This will be handled by FlightGlobe's hover events
  }, [filteredFlights]);

  const handleFlightClick = (flight: Flight | null) => {
    if (selectedFlight?.icao24 === flight?.icao24) {
      // Deselect if clicking the same flight
      setSelectedFlight(null);
      setCockpitView(false);
    } else {
      setSelectedFlight(flight);
      setCockpitView(flight !== null);
    }
  };

  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        margin: 0,
        padding: 0,
        overflow: 'hidden',
        background: '#000',
      }}
    >
      <FlightGlobe
        flights={filteredFlights}
        selectedFlight={selectedFlight}
        cockpitView={cockpitView}
        onFlightClick={handleFlightClick}
        onFlightHover={setHoveredFlight}
      />

      <FlightFiltersComponent
        filters={filters}
        onFiltersChange={setFilters}
      />

      <StatusBar
        connectionStatus={connectionStatus}
        error={error}
        stats={stats}
        lastUpdate={lastUpdate}
      />

      {/* Cockpit View Controls */}
      {selectedFlight && (
        <div
          style={{
            position: 'absolute',
            top: 20,
            right: 20,
            background: 'rgba(0, 0, 0, 0.8)',
            color: 'white',
            padding: '15px',
            borderRadius: '8px',
            zIndex: 1000,
          }}
        >
          <div style={{ marginBottom: '10px' }}>
            <strong>Selected: {selectedFlight.callsign || selectedFlight.icao24}</strong>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input
              type="checkbox"
              checked={cockpitView}
              onChange={(e) => setCockpitView(e.target.checked)}
            />
            Cockpit View
          </label>
          <button
            onClick={() => {
              setSelectedFlight(null);
              setCockpitView(false);
            }}
            style={{
              marginTop: '10px',
              width: '100%',
              padding: '5px',
              borderRadius: '4px',
              border: 'none',
              background: '#666',
              color: 'white',
              cursor: 'pointer',
            }}
          >
            Clear Selection
          </button>
        </div>
      )}

      {/* Tooltip */}
      {hoveredFlight && mousePosition && (
        <FlightTooltip flight={hoveredFlight} position={mousePosition} />
      )}
    </div>
  );
}

export default App;
