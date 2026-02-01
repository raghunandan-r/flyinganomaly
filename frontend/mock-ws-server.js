/**
 * Mock WebSocket server for testing frontend without backend
 * Reads from fixtures/opensky_nyc_sample.jsonl and simulates the WebSocket protocol
 * 
 * Usage: node mock-ws-server.js
 * Then set VITE_WS_URL=ws://localhost:8001/ws/flights in frontend
 */

const WebSocket = require('ws');
const fs = require('fs');
const path = require('path');

const PORT = 8001;
const DELTA_INTERVAL_MS = 200; // 5 Hz updates
const FIXTURE_FILE = path.join(__dirname, '../fixtures/opensky_nyc_sample.jsonl');

// Read fixture data
let fixtureData = [];
try {
  const content = fs.readFileSync(FIXTURE_FILE, 'utf-8');
  fixtureData = content
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line));
  console.log(`Loaded ${fixtureData.length} flight records from fixture`);
} catch (error) {
  console.error(`Failed to load fixture file: ${error.message}`);
  process.exit(1);
}

// Convert fixture envelopes to Flight format
function envelopeToFlight(envelope) {
  const payload = envelope.payload;
  return {
    icao24: payload.icao24,
    callsign: payload.callsign,
    position: payload.position,
    altitude_m: payload.altitude_m,
    heading_deg: payload.heading_deg,
    velocity_mps: payload.velocity_mps,
    vertical_rate_mps: payload.vertical_rate_mps,
    on_ground: payload.on_ground,
    status: 'NORMAL',
    geo_altitude_m: payload.geo_altitude_m,
    squawk: payload.squawk,
    spi: payload.spi,
    time_position_unix: payload.time_position_unix,
    last_contact_unix: payload.last_contact_unix,
  };
}

// Group flights by icao24 and simulate updates
const flightsByIcao = new Map();
fixtureData.forEach((envelope) => {
  const flight = envelopeToFlight(envelope);
  flightsByIcao.set(flight.icao24, flight);
});

const allFlights = Array.from(flightsByIcao.values());

// Create WebSocket server
const wss = new WebSocket.Server({ port: PORT });

console.log(`Mock WebSocket server running on ws://localhost:${PORT}/ws/flights`);

wss.on('connection', (ws, req) => {
  console.log('Client connected');

  // Send initial snapshot
  const snapshot = {
    type: 'snapshot',
    timestamp: new Date().toISOString(),
    sequence: 0,
    flights: allFlights,
  };
  ws.send(JSON.stringify(snapshot));
  console.log(`Sent snapshot with ${allFlights.length} flights`);

  // Simulate delta updates
  let sequence = 1;
  let flightIndex = 0;

  const deltaInterval = setInterval(() => {
    if (ws.readyState !== WebSocket.OPEN) {
      clearInterval(deltaInterval);
      return;
    }

    // Rotate through flights to simulate movement
    const numUpdates = Math.min(5, allFlights.length); // Update up to 5 flights per delta
    const upserts = [];
    const removed = [];

    for (let i = 0; i < numUpdates; i++) {
      const flight = allFlights[flightIndex % allFlights.length];
      
      // Simulate position change
      const updatedFlight = {
        ...flight,
        position: {
          lat: flight.position.lat + (Math.random() - 0.5) * 0.01,
          lon: flight.position.lon + (Math.random() - 0.5) * 0.01,
        },
        altitude_m: flight.altitude_m
          ? flight.altitude_m + (Math.random() - 0.5) * 50
          : null,
        heading_deg: flight.heading_deg
          ? (flight.heading_deg + Math.random() * 2 - 1) % 360
          : null,
        last_contact_unix: Math.floor(Date.now() / 1000),
      };

      upserts.push(updatedFlight);
      flightIndex++;
    }

    // Occasionally remove a flight (simulate leaving area)
    if (Math.random() < 0.1 && allFlights.length > 0) {
      const toRemove = allFlights[Math.floor(Math.random() * allFlights.length)];
      removed.push(toRemove.icao24);
    }

    const delta = {
      type: 'delta',
      timestamp: new Date().toISOString(),
      sequence: sequence++,
      upserts,
      removed,
    };

    ws.send(JSON.stringify(delta));
  }, DELTA_INTERVAL_MS);

  ws.on('close', () => {
    console.log('Client disconnected');
    clearInterval(deltaInterval);
  });

  ws.on('error', (error) => {
    console.error('WebSocket error:', error);
    clearInterval(deltaInterval);
  });
});

console.log('Mock server ready. Connect frontend to ws://localhost:8001/ws/flights');
