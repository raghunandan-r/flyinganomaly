/**
 * WebSocket hook for managing flight data stream
 * Handles Snapshot + Delta merging as per architecture spec
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import type {
  Flight,
  FlightState,
  WebSocketMessage,
  SnapshotMessage,
  DeltaMessage,
} from '../types/flight';

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws/flights';
const RECONNECT_DELAY_INITIAL = 1000; // Start with 1 second
const RECONNECT_DELAY_MAX = 30000; // Max 30 seconds
const RECONNECT_DELAY_MULTIPLIER = 1.5;

export function useFlightStream() {
  const [state, setState] = useState<FlightState>({
    flights: new Map(),
    lastUpdate: null,
    sequence: 0,
    connectionStatus: 'disconnected',
    error: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectDelayRef = useRef<number>(RECONNECT_DELAY_INITIAL);
  const flightsRef = useRef<Map<string, Flight>>(new Map());

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return; // Already connected
    }

    setState((prev) => ({
      ...prev,
      connectionStatus: 'connecting',
      error: null,
    }));

    try {
      const ws = new WebSocket(WS_URL, ['json']);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('WebSocket connected');
        reconnectDelayRef.current = RECONNECT_DELAY_INITIAL;
        setState((prev) => ({
          ...prev,
          connectionStatus: 'connected',
          error: null,
        }));
      };

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          handleMessage(message);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
          setState((prev) => ({
            ...prev,
            error: `Parse error: ${error instanceof Error ? error.message : 'Unknown error'}`,
          }));
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setState((prev) => ({
          ...prev,
          connectionStatus: 'error',
          error: 'WebSocket connection error',
        }));
      };

      ws.onclose = () => {
        console.log('WebSocket closed');
        wsRef.current = null;
        setState((prev) => ({
          ...prev,
          connectionStatus: 'disconnected',
        }));

        // Exponential backoff reconnection
        const delay = Math.min(
          reconnectDelayRef.current,
          RECONNECT_DELAY_MAX
        );
        reconnectTimeoutRef.current = window.setTimeout(() => {
          reconnectDelayRef.current *= RECONNECT_DELAY_MULTIPLIER;
          connect();
        }, delay);
      };
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      setState((prev) => ({
        ...prev,
        connectionStatus: 'error',
        error: `Connection failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
      }));
    }
  }, []);

  const handleMessage = useCallback((message: WebSocketMessage) => {
    const now = new Date();

    if (message.type === 'snapshot') {
      const snapshot = message as SnapshotMessage;
      const flights = new Map<string, Flight>();

      snapshot.flights.forEach((flight) => {
        flights.set(flight.icao24, flight);
      });

      flightsRef.current = flights;
      setState({
        flights,
        lastUpdate: now,
        sequence: snapshot.sequence,
        connectionStatus: 'connected',
        error: null,
      });
    } else if (message.type === 'delta') {
      const delta = message as DeltaMessage;
      const flights = new Map(flightsRef.current);

      // Apply upserts
      delta.upserts.forEach((flight) => {
        flights.set(flight.icao24, flight);
      });

      // Apply removals
      delta.removed.forEach((icao24) => {
        flights.delete(icao24);
      });

      flightsRef.current = flights;
      setState((prev) => ({
        flights,
        lastUpdate: now,
        sequence: delta.sequence,
        connectionStatus: 'connected',
        error: null,
      }));
    } else if (message.type === 'anomaly') {
      // Update flight status to ANOMALY
      const flights = new Map(flightsRef.current);
      const flight = flights.get(message.payload.icao24);
      if (flight) {
        flights.set(message.payload.icao24, {
          ...flight,
          status: 'ANOMALY',
        });
        flightsRef.current = flights;
        setState((prev) => ({
          ...prev,
          flights,
          lastUpdate: now,
        }));
      }
    }
  }, []);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  useEffect(() => {
    connect();

    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    flights: Array.from(state.flights.values()),
    lastUpdate: state.lastUpdate,
    sequence: state.sequence,
    connectionStatus: state.connectionStatus,
    error: state.error,
    reconnect: connect,
  };
}
