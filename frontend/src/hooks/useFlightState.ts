/**
 * Hook for managing filtered and processed flight state
 */

import { useMemo } from 'react';
import type { Flight, FlightFilters } from '../types/flight';
import { isStale } from '../utils/interpolation';

export function useFlightState(
  flights: Flight[],
  filters: FlightFilters
) {
  const filteredFlights = useMemo(() => {
    return flights.filter((flight) => {
      // Altitude filter
      if (flight.altitude_m !== null) {
        if (filters.minAltitude !== null && flight.altitude_m < filters.minAltitude) {
          return false;
        }
        if (filters.maxAltitude !== null && flight.altitude_m > filters.maxAltitude) {
          return false;
        }
      }

      // Ground filter
      if (!filters.showGround && flight.on_ground) {
        return false;
      }

      // Callsign search
      if (filters.callsignSearch) {
        const searchLower = filters.callsignSearch.toLowerCase();
        const callsign = flight.callsign?.toLowerCase() || '';
        const icao24 = flight.icao24.toLowerCase();
        if (!callsign.includes(searchLower) && !icao24.includes(searchLower)) {
          return false;
        }
      }

      return true;
    });
  }, [flights, filters]);

  const stats = useMemo(() => {
    const total = flights.length;
    const filtered = filteredFlights.length;
    const inAir = flights.filter((f) => !f.on_ground).length;
    const stale = flights.filter((f) => isStale(f)).length;

    return {
      total,
      filtered,
      inAir,
      stale,
    };
  }, [flights, filteredFlights]);

  return {
    filteredFlights,
    stats,
  };
}
