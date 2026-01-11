# Parallel Implementation Plan for SkySentinel v4.0

**Objective:** Split the implementation of SkySentinel into 5 independent, parallel workstreams that can be executed by separate Cursor/AI agents simultaneously.

**Prerequisites:**
- The `docs/` folder contains the "Single Source of Truth":
    - `docs/final_architecture.md` (The Contract)
    - `docs/final_phase1.md` (Live Viz)
    - `docs/final_phase2.md` (History/Anomalies)

---

## 🏗️ Stream A: Infrastructure & Database (The Foundation)

**Goal:** Establish the runtime environment and data storage.
**Agent Context:** `docs/final_architecture.md` (Sections 10 & 11), `docs/final_phase2.md` (Section 3).

**Tasks:**
1.  **Docker Compose:** Create `docker-compose.yml` merging Phase 1 and 2 services. Ensure health checks and networks are correct.
2.  **Configuration:** Create `.env` and `.env.example` with all variables defined in Architecture Section 10.2.
3.  **Database:** Create `database/init.sql` with PostGIS extensions, full schema, indexes, and stored procedures as defined in Phase 2 Section 3.2.
4.  **Static Data:** Create `static/airports.geojson` (download or generate dummy data matching the schema in Architecture Section 4.1).

**Definition of Done:**
- `docker compose up` starts Redpanda and Postgres (healthy).
- `docker exec postgres psql -U skysentinel -c '\dt'` shows all tables (`flights_current`, `flights_history`, `anomalies`).

---

## 📡 Stream B: Ingestion (The Source)

**Goal:** Get data into Redpanda.
**Agent Context:** `docs/final_architecture.md` (Sections 3 & 6.1), `docs/final_phase1.md` (Section 4.2).

**Tasks:**
1.  **Environment:** Create `ingestion/requirements.txt` and `ingestion/Dockerfile`.
2.  **Producer:** Implement `ingestion/producer_flight.py` using `confluent-kafka`.
    - Must publish to **both** `flights.state` (compacted) and `flights.updates` (append-only).
    - Must implement the exact `FlightEnvelope` JSON schema.
3.  **Replay Mode:** Implement logic to read from `REPLAY_FILE` and simulate timing.
4.  **Fixtures:** **CRITICAL:** Create a dummy `fixtures/opensky_nyc_sample.jsonl` with valid JSON envelopes so other streams can test.

**Definition of Done:**
- Running `docker compose up producer` logs "Published X flights".
- `rpk topic consume flights.state` shows valid JSON messages.

---

## ⚙️ Stream C: Backend (The Hub)

**Goal:** Serve the API and WebSockets.
**Agent Context:** `docs/final_architecture.md` (Sections 3, 6.2, 8), `docs/final_phase1.md` (Section 4.3).

**Tasks:**
1.  **Environment:** Create `backend/requirements.txt` and `backend/Dockerfile`.
2.  **Consumer:** Implement `backend/consumer.py` to consume `flights.state`.
    - Implement `FlightCache` with out-of-order rejection (logic in Phase 1 docs).
3.  **WebSocket:** Implement `backend/websocket.py` and `backend/main.py`.
    - Broadcast "Snapshot" on connect.
    - Broadcast "Delta" updates (upsert/remove) at 2-5Hz.
4.  **Metrics:** Expose Prometheus metrics at `/metrics`.

**Definition of Done:**
- Can connect via `wscat` or Postman to `ws://localhost:8000/ws/flights` and receive JSON.
- `GET /flights` returns current state snapshot.

---

## 🖥️ Stream D: Frontend (The UI)

**Goal:** Visualize the data.
**Agent Context:** `docs/final_architecture.md` (Section 8), `docs/final_phase1.md` (Section 4.4).

**Tasks:**
1.  **Setup:** Scaffold Vite + React + TypeScript in `frontend/`.
2.  **Globe:** Implement `Globe.gl` component (`components/FlightGlobe.tsx`).
3.  **State:** Implement `useFlightStream` hook to handle WebSocket "Snapshot" + "Delta" merging.
4.  **Features:** Add filters (Altitude, Ground) and Cockpit View.
5.  **Mocking:** Use a mock WebSocket server or the `fixtures/` file if Backend isn't ready yet.

**Definition of Done:**
- UI loads on `http://localhost:3000`.
- Connects to backend WS.
- Renders moving aircraft dots (even if data is fake).

---

## 🧠 Stream E: Processing (The Intelligence - Phase 2)

**Goal:** Detect anomalies and write history.
**Agent Context:** `docs/final_architecture.md` (Sections 5 & 6.3), `docs/final_phase2.md` (Section 4).

**Tasks:**
1.  **Environment:** Setup `processing/` with Bytewax.
2.  **Logic:** Implement:
    - `smoothing.py` (Kalman Filter)
    - `anomaly_detector.py` (Logic for Descent, Go-Around, etc.)
    - `db_writer.py` (Postgres sink)
3.  **Pipeline:** Connect `flights.updates` (Kafka) -> Logic -> Postgres/Kafka (`flights.anomalies`).

**Definition of Done:**
- Reading from `flights.updates` results in rows in Postgres `flights_history` table.
- Anomaly events appear in `flights.anomalies` topic.

---

## 🤝 Integration Strategy

1.  **Orchestrator Role:** Maintains `deployment_status.md` to track which streams are ready.
2.  **Order of Operations:**
    - Run **Stream A** (Infra) first.
    - Run **Stream B** (Ingestion) in "Replay Mode".
    - Once B is running, Stream C, D, and E can be developed in parallel against the live Kafka stream.
3.  **Contract Enforcement:**
    - Do **NOT** change topic names.
    - Do **NOT** change JSON schemas.
    - If a schema change is needed, update `docs/final_architecture.md` first.
