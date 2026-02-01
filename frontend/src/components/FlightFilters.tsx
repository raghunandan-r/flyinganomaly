/**
 * FlightFilters component for filtering flights
 */

import { useState } from 'react';
import type { FlightFilters } from '../types/flight';

interface FlightFiltersProps {
  filters: FlightFilters;
  onFiltersChange: (filters: FlightFilters) => void;
}

export function FlightFiltersComponent({
  filters,
  onFiltersChange,
}: FlightFiltersProps) {
  const [localFilters, setLocalFilters] = useState<FlightFilters>(filters);

  const handleChange = (updates: Partial<FlightFilters>) => {
    const newFilters = { ...localFilters, ...updates };
    setLocalFilters(newFilters);
    onFiltersChange(newFilters);
  };

  return (
    <div
      style={{
        position: 'absolute',
        top: 20,
        left: 20,
        background: 'rgba(0, 0, 0, 0.8)',
        color: 'white',
        padding: '20px',
        borderRadius: '8px',
        minWidth: '250px',
        zIndex: 1000,
      }}
    >
      <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Filters</h3>

      {/* Altitude Range */}
      <div style={{ marginBottom: '15px' }}>
        <label style={{ display: 'block', marginBottom: '5px' }}>
          Min Altitude (m)
        </label>
        <input
          type="number"
          value={localFilters.minAltitude || ''}
          onChange={(e) =>
            handleChange({
              minAltitude: e.target.value ? parseInt(e.target.value) : null,
            })
          }
          placeholder="No limit"
          style={{
            width: '100%',
            padding: '5px',
            borderRadius: '4px',
            border: '1px solid #ccc',
          }}
        />
      </div>

      <div style={{ marginBottom: '15px' }}>
        <label style={{ display: 'block', marginBottom: '5px' }}>
          Max Altitude (m)
        </label>
        <input
          type="number"
          value={localFilters.maxAltitude || ''}
          onChange={(e) =>
            handleChange({
              maxAltitude: e.target.value ? parseInt(e.target.value) : null,
            })
          }
          placeholder="No limit"
          style={{
            width: '100%',
            padding: '5px',
            borderRadius: '4px',
            border: '1px solid #ccc',
          }}
        />
      </div>

      {/* Show Ground Flights */}
      <div style={{ marginBottom: '15px' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <input
            type="checkbox"
            checked={localFilters.showGround}
            onChange={(e) =>
              handleChange({ showGround: e.target.checked })
            }
          />
          Show Ground Flights
        </label>
      </div>

      {/* Callsign Search */}
      <div style={{ marginBottom: '15px' }}>
        <label style={{ display: 'block', marginBottom: '5px' }}>
          Search (Callsign/ICAO24)
        </label>
        <input
          type="text"
          value={localFilters.callsignSearch}
          onChange={(e) =>
            handleChange({ callsignSearch: e.target.value })
          }
          placeholder="e.g., UAL123"
          style={{
            width: '100%',
            padding: '5px',
            borderRadius: '4px',
            border: '1px solid #ccc',
          }}
        />
      </div>

      {/* Reset Button */}
      <button
        onClick={() => {
          const resetFilters: FlightFilters = {
            minAltitude: null,
            maxAltitude: null,
            showGround: true,
            callsignSearch: '',
          };
          setLocalFilters(resetFilters);
          onFiltersChange(resetFilters);
        }}
        style={{
          width: '100%',
          padding: '8px',
          borderRadius: '4px',
          border: 'none',
          background: '#666',
          color: 'white',
          cursor: 'pointer',
        }}
      >
        Reset Filters
      </button>
    </div>
  );
}
