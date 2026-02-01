/**
 * Interpolation utilities for smooth flight animation
 */

import type { Flight, Position } from '../types/flight';

export interface InterpolatedFlight extends Flight {
  interpolatedPosition: Position;
  age_ms: number; // Time since last update in milliseconds
}

/**
 * Calculate interpolated position based on velocity and heading
 * Used for "ghost" visualization when data is stale
 */
export function interpolatePosition(
  flight: Flight,
  age_ms: number
): Position {
  const { position, velocity_mps, heading_deg } = flight;

  if (!velocity_mps || !heading_deg || age_ms <= 0) {
    return position;
  }

  // Convert heading to radians (0 = North, clockwise)
  const headingRad = ((heading_deg - 90) * Math.PI) / 180;

  // Calculate distance traveled (meters)
  const distance_m = (velocity_mps * age_ms) / 1000;

  // Approximate meters to degrees (at NYC latitude ~40.7)
  // 1 degree latitude ≈ 111,000 m
  // 1 degree longitude ≈ 85,000 m (at 40.7° latitude)
  const latDelta = (distance_m * Math.cos(headingRad)) / 111000;
  const lonDelta = (distance_m * Math.sin(headingRad)) / 85000;

  return {
    lat: position.lat + latDelta,
    lon: position.lon + lonDelta,
  };
}

/**
 * Create interpolated flight for ghost visualization
 */
export function createGhostFlight(
  flight: Flight,
  lastUpdateTime: Date
): InterpolatedFlight {
  const now = new Date();
  const age_ms = now.getTime() - lastUpdateTime.getTime();

  return {
    ...flight,
    interpolatedPosition: interpolatePosition(flight, age_ms),
    age_ms,
  };
}

/**
 * Check if flight data is stale (for ghost visualization)
 */
export function isStale(flight: Flight, threshold_ms: number = 30000): boolean {
  if (!flight.last_contact_unix) {
    return true;
  }

  const now = Date.now() / 1000; // Convert to seconds
  const age_seconds = now - flight.last_contact_unix;
  return age_seconds * 1000 > threshold_ms;
}
