# SkySentinel Test Suite

This directory contains comprehensive tests for the SkySentinel system, including smoke tests, integration tests, and contract tests.

## Test Structure

```
tests/
├── smoke/              # End-to-end smoke tests
│   ├── test_full_pipeline.py
│   ├── test_anomaly_detection.py
│   └── test_replay_mode.py
├── integration/        # Integration tests for cross-service contracts
│   ├── test_websocket_protocol.py
│   ├── test_database_writes.py
│   └── test_kafka_topics.py
└── contract/           # Contract tests (from Stream G)
    ├── test_producer_contract.py
    ├── test_backend_contract.py
    └── test_processing_contract.py
```

## Prerequisites

1. **Docker Compose**: Services must be running
   ```bash
   docker compose up -d
   ```

2. **Python Dependencies**: Install test requirements
   ```bash
   pip install -r tests/requirements.txt
   ```

3. **Environment Variables**: Set if using non-default values
   ```bash
   export KAFKA_BROKER=localhost:9092
   export BACKEND_WS_URL=ws://localhost:8000/ws/flights
   export POSTGRES_HOST=localhost
   export POSTGRES_PORT=5432
   export POSTGRES_DB=skysentinel
   export POSTGRES_USER=skysentinel
   export POSTGRES_PASSWORD=skysentinel
   ```

## Running Tests

### Run All Tests

```bash
# From project root
pytest tests/
```

### Run Smoke Tests Only

```bash
pytest tests/smoke/
```

Smoke tests verify end-to-end functionality:
- **test_full_pipeline.py**: Producer → Backend → Frontend flow
- **test_anomaly_detection.py**: Anomaly detection and WebSocket broadcasting
- **test_replay_mode.py**: Replay mode consistency and determinism

### Run Integration Tests Only

```bash
pytest tests/integration/
```

Integration tests verify cross-service contracts:
- **test_websocket_protocol.py**: WebSocket message formats and protocols
- **test_database_writes.py**: Database schema and data integrity
- **test_kafka_topics.py**: Kafka topic configurations and message formats

### Run Contract Tests Only

```bash
pytest tests/contract/
```

Contract tests verify schema compliance (requires Stream G completion).

### Run Specific Test File

```bash
pytest tests/smoke/test_full_pipeline.py
```

### Run Specific Test Function

```bash
pytest tests/smoke/test_full_pipeline.py::test_end_to_end_flow
```

### Run with Verbose Output

```bash
pytest tests/ -v
```

### Run with Coverage

```bash
pytest tests/ --cov=. --cov-report=html
```

## Test Fixtures

Test fixtures are located in `fixtures/opensky_nyc_sample.jsonl` and include:

1. **Normal Flight Scenarios**: Standard flight updates
2. **Anomaly Scenarios**:
   - Emergency descent (rapid altitude loss)
   - Go-around (approach abort)
   - Emergency squawk (7700)
3. **Edge Cases**:
   - Missing fields
   - Null values
   - Incomplete data

## Test Scenarios

### Smoke Tests

#### Full Pipeline Test
- Verifies producer publishes to Kafka
- Verifies backend consumes and serves via WebSocket
- Verifies frontend can receive messages
- Tests complete end-to-end flow

#### Anomaly Detection Test
- Publishes flight updates that trigger anomalies
- Verifies anomalies are published to Kafka
- Verifies anomalies are broadcast via WebSocket
- Tests emergency descent and squawk scenarios

#### Replay Mode Test
- Verifies replay reads from fixtures correctly
- Verifies message ordering is preserved
- Verifies timestamp sequences
- Verifies deterministic replay behavior

### Integration Tests

#### WebSocket Protocol Test
- Validates snapshot message format
- Validates delta message format
- Validates anomaly message format
- Verifies sequence numbers are monotonic
- Verifies timestamps are valid

#### Database Writes Test
- Verifies tables exist with correct schema
- Verifies data integrity
- Verifies PostGIS extension is enabled
- Verifies geography columns work correctly

#### Kafka Topics Test
- Verifies topics exist
- Validates message formats match schemas
- Verifies topics are keyed correctly

## Adding New Tests

### Adding a New Smoke Test

1. Create test file in `tests/smoke/`
2. Use pytest fixtures for setup/teardown
3. Follow naming convention: `test_*.py`
4. Add test functions prefixed with `test_`

Example:
```python
def test_new_feature():
    """Test description."""
    # Test implementation
    assert condition
```

### Adding a New Integration Test

1. Create test file in `tests/integration/`
2. Test cross-service contracts
3. Use appropriate fixtures (database, Kafka, WebSocket)
4. Validate message formats and schemas

### Adding Test Fixtures

1. Add scenarios to `fixtures/opensky_nyc_sample.jsonl`
2. Follow JSON envelope format
3. Include edge cases and anomaly scenarios
4. Document scenarios in test comments

## Troubleshooting

### Tests Fail to Connect

- Ensure Docker Compose services are running: `docker compose ps`
- Check service health: `docker compose logs <service>`
- Verify environment variables are set correctly

### Kafka Consumer Timeout

- Check Kafka/Redpanda is running: `docker logs redpanda`
- Verify topics exist: `rpk topic list`
- Check network connectivity

### Database Connection Failed

- Verify Postgres is running: `docker logs postgres`
- Check credentials in `.env` file
- Verify database exists: `docker exec postgres psql -U skysentinel -c '\l'`

### WebSocket Connection Failed

- Check backend is running: `docker logs backend_api`
- Verify WebSocket endpoint: `curl http://localhost:8000/docs`
- Check firewall/port settings

## Continuous Integration

Tests are designed to run in CI/CD pipelines:

```yaml
# Example GitHub Actions
- name: Run Tests
  run: |
    docker compose up -d
    sleep 10  # Wait for services to be ready
    pytest tests/ -v
```

## Test Maintenance

- Update tests when schemas change
- Add tests for new features
- Keep fixtures up to date with real data patterns
- Document test scenarios and expected behaviors

## Related Documentation

- Architecture: `docs/final_architecture.md`
- Deployment Status: `deployment_status.md`
- Multi-Agent Plan: `docs/multi_agent_plan.md`
