# SkySentinel Frontend

React + TypeScript frontend for real-time flight visualization using Globe.gl.

## Features

- **3D Globe Visualization**: Interactive 3D globe showing live flight positions
- **Real-time Updates**: WebSocket connection for live flight data
- **Filters**: Filter by altitude, ground status, and callsign search
- **Cockpit View**: Camera lock on selected aircraft
- **Ghost Interpolation**: Visual indicator for stale data
- **Flight Tooltips**: Hover to see detailed flight information

## Development

### Prerequisites

- Node.js 20+
- npm or yarn

### Setup

```bash
# Install dependencies
npm install

# Start development server
npm run dev
```

The app will be available at `http://localhost:3000`

### Mock WebSocket Server

If the backend is not available, you can use the mock WebSocket server:

```bash
# In a separate terminal
npm run mock-ws
```

Then set the environment variable:
```bash
export VITE_WS_URL=ws://localhost:8001/ws/flights
npm run dev
```

Or create a `.env.local` file:
```
VITE_WS_URL=ws://localhost:8001/ws/flights
```

## Building for Production

```bash
npm run build
```

The built files will be in the `dist/` directory.

## Docker

The frontend can be built and run using Docker:

```bash
docker build -t skysentinel-frontend .
docker run -p 3000:3000 skysentinel-frontend
```

Or use docker-compose from the project root:

```bash
docker compose up frontend
```

## Architecture

- **Components**: React components for UI
  - `FlightGlobe.tsx`: Main 3D globe visualization
  - `FlightFilters.tsx`: Filter controls
  - `StatusBar.tsx`: Connection status and statistics
  - `FlightTooltip.tsx`: Hover tooltip

- **Hooks**: Custom React hooks
  - `useFlightStream.ts`: WebSocket connection and message handling
  - `useFlightState.ts`: Flight filtering and statistics

- **Types**: TypeScript type definitions
  - `flight.ts`: Flight data structures

- **Utils**: Utility functions
  - `interpolation.ts`: Ghost flight interpolation
  - `msgpack.ts`: MessagePack support (placeholder)

## WebSocket Protocol

The frontend expects WebSocket messages in the following format:

### Snapshot (on connect)
```json
{
  "type": "snapshot",
  "timestamp": "2026-01-09T12:00:00.000Z",
  "sequence": 0,
  "flights": [...]
}
```

### Delta (continuous updates)
```json
{
  "type": "delta",
  "timestamp": "2026-01-09T12:00:10.000Z",
  "sequence": 43,
  "upserts": [...],
  "removed": ["icao24", ...]
}
```

See `docs/final_architecture.md` Section 8 for full protocol specification.
