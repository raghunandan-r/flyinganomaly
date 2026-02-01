# Parallel Implementation Plan for SkySentinel v4.0

**Objective:** Split the implementation of SkySentinel into independent, parallel workstreams that can be executed by separate Cursor/AI agents simultaneously.

**Current Status:**
- **Streams A-E:** ✅ Initial implementation complete (see `deployment_status.md` for details)
- **Streams F-I:** 🔄 New streams for fixing integration gaps, enforcing contracts, testing, and coordination

**Prerequisites:**
- The `docs/` folder contains the "Single Source of Truth":
    - `docs/final_architecture.md` (The Contract)
    - `docs/final_phase1.md` (Live Viz)
    - `docs/final_phase2.md` (History/Anomalies)

**Coordination Model:**
- All agents work on the **same branch** (no branching strategy)
- Agents coordinate via `deployment_status.md` updates
- **Integration Agent (Stream I)** keeps services running and verifies work
- Agents must check `deployment_status.md` before starting and update it after completing tasks
- See "Integration Strategy" section below for full details

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

---

## 🔧 Stream F: Integration Fixes & Missing Connections

**Goal:** Fix integration gaps identified between streams (anomaly stream, metrics, etc.)
**Agent Context:** `docs/final_architecture.md` (Sections 6.2, 6.3, 8), analysis of current implementation gaps.

**Tasks:**
1.  **Anomaly Stream Integration:** 
    - Implement `backend/anomaly_consumer.py` to consume `flights.anomalies` topic.
    - Wire anomaly events into `ConnectionManager` to broadcast via WebSocket.
    - Ensure anomaly messages match `AnomalyMessage` format expected by frontend.
2.  **Processing Metrics:**
    - Add Prometheus metrics server to `processing/run.py` or `processing/pipeline.py`.
    - Expose metrics at port `8080` (matching `prometheus/prometheus.yml` scrape config).
    - Add metrics: `processing_messages_processed_total`, `processing_anomalies_detected_total`, `processing_db_write_latency_seconds`.
3.  **Topic Configuration:**
    - Create `scripts/init_topics.sh` or `scripts/init_topics.py` to ensure topics exist with correct config:
      - `flights.state`: compaction enabled, keyed by `icao24`
      - `flights.updates`: append-only, 7d retention
      - `flights.anomalies`: append-only, 30d retention
    - Add topic initialization to `docker-compose.yml` as init container or startup script.
4.  **Replay Mode Fixes:**
    - Fix replay timing logic in `ingestion/producer_flight.py` to ensure deterministic behavior.
    - Ensure replay preserves message ordering and timing correctly.

**Definition of Done:**
- Anomaly events from processing appear in WebSocket messages to frontend.
- `curl http://processing:8080/metrics` returns Prometheus metrics.
- Topics are created with correct configs on `docker compose up`.
- Replay mode produces consistent, deterministic output.

**Deployment Status Updates:**
- Mark Stream F tasks as complete in `deployment_status.md` with verification commands.

---

## 🛡️ Stream G: Contract Enforcement & Schema Validation

**Goal:** Create enforceable contract artifacts and validation across services.
**Agent Context:** `docs/final_architecture.md` (Sections 3, 8), current implementation.

**Tasks:**
1.  **Schema Artifacts:**
    - Create `contracts/schemas/` directory with JSON Schema files:
      - `flight_envelope.json` (FlightStateEnvelope, FlightUpdateEnvelope)
      - `anomaly_envelope.json` (AnomalyEventEnvelope)
      - `websocket_messages.json` (SnapshotMessage, DeltaMessage, AnomalyMessage)
    - Create `contracts/examples/` with golden JSON files showing correct message formats.
2.  **Shared Constants:**
    - Create `contracts/constants.py` (Python) and `contracts/constants.ts` (TypeScript) with:
      - Topic names (`KAFKA_TOPIC_STATE`, `KAFKA_TOPIC_UPDATES`, `KAFKA_TOPIC_ANOMALIES`)
      - Message types (`flight_state`, `flight_update`, `anomaly_event`)
      - Schema versions
    - Update all services to import from these constants (or document why not).
3.  **Validation Libraries:**
    - Create `contracts/validation.py` with Pydantic models matching schemas.
    - Update producer to validate envelopes before publishing.
    - Update backend consumer to validate envelopes before processing.
    - Update processing pipeline to validate envelopes before processing.
4.  **Contract Tests:**
    - Create `tests/contract/` directory with:
      - `test_producer_contract.py`: validates producer output matches schema
      - `test_backend_contract.py`: validates backend WS messages match schema
      - `test_processing_contract.py`: validates processing output matches schema
    - These tests should run independently (no full stack required).

**Definition of Done:**
- All services validate messages against schemas before processing.
- Contract tests pass for all services.
- Schema changes require updating `contracts/schemas/` first (fail-fast on drift).

**Deployment Status Updates:**
- Mark Stream G tasks as complete in `deployment_status.md` with test commands.

---

## 🧪 Stream H: End-to-End Testing & Smoke Tests

**Goal:** Create comprehensive test suite and smoke test harness.
**Agent Context:** `docs/final_architecture.md`, `docs/final_phase1.md`, `docs/final_phase2.md`.

**Tasks:**
1.  **Smoke Test Suite:**
    - Create `tests/smoke/` directory with:
      - `test_full_pipeline.py`: end-to-end test from producer → backend → frontend
      - `test_anomaly_detection.py`: verify anomalies flow through entire pipeline
      - `test_replay_mode.py`: verify replay produces consistent results
    - Tests should use docker-compose services or testcontainers.
2.  **Integration Test Harness:**
    - Create `tests/integration/` with:
      - `test_websocket_protocol.py`: verify WS snapshot/delta/anomaly messages
      - `test_database_writes.py`: verify processing writes to Postgres correctly
      - `test_kafka_topics.py`: verify topic configurations and message formats
3.  **Test Fixtures:**
    - Enhance `fixtures/opensky_nyc_sample.jsonl` with:
      - Known anomaly scenarios (emergency descent, go-around, etc.)
      - Edge cases (missing fields, null values, etc.)
      - Timestamp sequences for deterministic replay testing
4.  **Test Documentation:**
    - Create `tests/README.md` explaining:
      - How to run smoke tests
      - How to run integration tests
      - How to add new test scenarios

**Definition of Done:**
- Smoke tests pass against full stack.
- Integration tests verify all cross-service contracts.
- Test fixtures cover edge cases and anomaly scenarios.

**Deployment Status Updates:**
- Mark Stream H tasks as complete in `deployment_status.md` with test execution commands.

---

## 🔄 Stream I: Integration Agent (Orchestrator)

**Goal:** Keep services running, verify deployment status, coordinate agent work.
**Agent Context:** `deployment_status.md`, `docker-compose.yml`, all stream outputs.

**Tasks:**
1.  **Service Orchestration:**
    - Ensure `docker compose up` keeps all services healthy.
    - Monitor service health and restart if needed.
    - Keep services running continuously for smoke tests.
2.  **Deployment Status Verification:**
    - Read `deployment_status.md` regularly.
    - Verify each stream's "Definition of Done" criteria are actually met:
      - Run verification commands from deployment_status.md
      - Check that services are actually working (not just code exists)
    - Update `deployment_status.md` with verification results (pass/fail).
3.  **Smoke Test Execution:**
    - Run smoke tests from Stream H periodically (every N commits or on request).
    - Report test results in `deployment_status.md`.
    - Identify failures and mark blocking issues.
4.  **Coordination:**
    - Monitor for conflicts (multiple agents editing same files).
    - Ensure all agents update `deployment_status.md` after completing tasks.
    - Mark streams as "BLOCKED" if dependencies aren't ready.

**Definition of Done:**
- All services stay healthy and running.
- Deployment status accurately reflects reality (not just checkboxes).
- Smoke tests run automatically and results are tracked.

**Deployment Status Updates:**
- Continuously update `deployment_status.md` with:
  - Service health status
  - Test results
  - Blocking issues
  - Verification outcomes

---

## 🤝 Integration Strategy (Updated)

### Coordination Model

1.  **Single Branch Workflow:**
    - All agents work on the **same branch** (typically `main` or `develop`).
    - No branch merging strategy - direct commits to shared branch.
    - Agents coordinate via `deployment_status.md` updates.

2.  **Deployment Status as Coordination Hub:**
    - **Every agent MUST update `deployment_status.md`** after completing tasks.
    - Format: Mark tasks as `[x]` when done, include verification commands.
    - Agents check `deployment_status.md` before starting work to see what's ready.

3.  **Integration Agent (Stream I) Responsibilities:**
    - Keeps services running continuously (`docker compose up`).
    - Runs smoke tests periodically.
    - Verifies deployment status claims are accurate.
    - Updates `deployment_status.md` with verification results.
    - Marks streams as "BLOCKED" if dependencies aren't met.

4.  **Agent Workflow:**
    - Agent starts: Read `deployment_status.md` to see current state.
    - Agent works: Complete assigned tasks.
    - Agent completes: Update `deployment_status.md` with:
      - `[x]` checkboxes for completed tasks
      - Verification commands (how to test the work)
      - Any blocking issues or dependencies needed
    - Agent loops: Check `deployment_status.md` again - if dependencies ready, continue. If blocked, wait or work on other tasks.

5.  **Contract Enforcement:**
    - **Do NOT** change topic names without updating `contracts/constants.py` and `docs/final_architecture.md`.
    - **Do NOT** change JSON schemas without updating `contracts/schemas/` and running contract tests.
    - Schema changes require updating `docs/final_architecture.md` first (single source of truth).
    - Contract tests (Stream G) must pass before marking work complete.

6.  **Order of Operations (Initial Setup):**
    - Stream A (Infra) must complete first.
    - Stream B (Ingestion) can start once A is done.
    - Streams C, D, E can develop in parallel once B is running (replay mode).
    - Streams F, G, H, I run in parallel to fix/integrate/test.

7.  **Verification Loop:**
    - Integration Agent (Stream I) continuously verifies:
      - Services are healthy
      - Deployment status claims match reality
      - Smoke tests pass
    - Other agents check `deployment_status.md` before claiming work is done.
    - If Integration Agent marks something as "FAILED", the responsible agent must fix it.

### Example Deployment Status Entry Format

```markdown
## Stream F: Integration Fixes

- [x] Anomaly stream consumer implemented
  - Verification: `docker logs backend_api | grep anomaly`
  - Status: ✅ PASS - Anomalies appear in WS messages
  
- [x] Processing metrics exposed
  - Verification: `curl http://localhost:8080/metrics` (from processing container)
  - Status: ✅ PASS - Metrics endpoint responds
  
- [ ] Topic initialization script
  - Status: 🔄 IN PROGRESS
  - Blocked by: Need to verify Redpanda topic creation API
```

### Blocking Dependencies

- Stream F depends on: Stream C (backend), Stream E (processing) being complete
- Stream G depends on: All streams A-E complete (to validate their contracts)
- Stream H depends on: Stream F (integration fixes) complete, Stream G (contracts) complete
- Stream I (Integration Agent) runs continuously and depends on nothing (it's the coordinator)
