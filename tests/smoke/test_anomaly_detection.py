"""
Smoke test: Verify anomalies flow through entire pipeline.

This test verifies that:
1. Processing detects anomalies
2. Anomalies are published to Kafka
3. Backend consumes anomalies
4. Anomalies are broadcast via WebSocket
"""

import pytest
import json
import time
import os
from typing import List, Dict, Any
from confluent_kafka import Consumer, Producer, KafkaError
import websocket


KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
BACKEND_WS_URL = os.getenv("BACKEND_WS_URL", "ws://localhost:8000/ws/flights")
ANOMALIES_TOPIC = "flights.anomalies"
UPDATES_TOPIC = "flights.updates"
TEST_TIMEOUT = 60  # seconds (anomaly detection may take time)


class WebSocketClient:
    """Simple WebSocket client for testing."""
    
    def __init__(self, url: str):
        self.url = url
        self.messages: List[Dict[str, Any]] = []
        self.ws = None
        self.connected = False
        
    def connect(self, timeout: int = 10):
        """Connect to WebSocket."""
        try:
            self.ws = websocket.WebSocket()
            self.ws.connect(self.url, timeout=timeout)
            self.connected = True
        except Exception as e:
            pytest.fail(f"Failed to connect to WebSocket: {e}")
    
    def receive_messages(self, count: int = 1, timeout: int = 5) -> List[Dict[str, Any]]:
        """Receive messages from WebSocket."""
        if not self.connected:
            self.connect()
        
        messages = []
        start_time = time.time()
        
        while len(messages) < count and (time.time() - start_time) < timeout:
            try:
                self.ws.settimeout(timeout)
                message = self.ws.recv()
                data = json.loads(message)
                messages.append(data)
            except websocket.WebSocketTimeoutException:
                break
            except Exception as e:
                pytest.fail(f"Error receiving message: {e}")
        
        return messages
    
    def close(self):
        """Close WebSocket connection."""
        if self.ws:
            self.ws.close()
            self.connected = False


@pytest.fixture(scope="module")
def kafka_consumer():
    """Create Kafka consumer for anomalies topic."""
    consumer = Consumer({
        'bootstrap.servers': KAFKA_BROKER,
        'group.id': 'anomaly_test_consumer',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False
    })
    yield consumer
    consumer.close()


@pytest.fixture(scope="module")
def kafka_producer():
    """Create Kafka producer for test data."""
    producer = Producer({
        'bootstrap.servers': KAFKA_BROKER,
        'acks': 'all',
        'retries': 3
    })
    yield producer
    producer.flush()
    producer.close()


def create_emergency_descent_flight(icao24: str, base_time: int) -> List[Dict]:
    """Create flight updates that trigger emergency descent detection."""
    # Emergency descent: >3000 ft/min (15.24 m/s) sustained
    # Create 4 samples with rapid descent
    flights = []
    altitude = 10000.0  # Start at 10km
    descent_rate = -20.0  # m/s (exceeds threshold of 15.24 m/s)
    
    for i in range(4):
        flight = {
            "schema_version": 1,
            "type": "flight_update",
            "produced_at": f"2026-01-09T12:00:{i*10:02d}.000Z",
            "source": {
                "provider": "opensky",
                "mode": "replay",
                "bbox": {"lat_min": 40.40, "lat_max": 41.20, "lon_min": -74.50, "lon_max": -73.50},
                "poll_interval_s": 10
            },
            "payload": {
                "icao24": icao24,
                "callsign": "EMERG",
                "position": {"lat": 40.6413 + i*0.001, "lon": -73.7781 + i*0.001},
                "altitude_m": altitude,
                "geo_altitude_m": altitude + 50,
                "velocity_mps": 150.0,
                "heading_deg": 270.0,
                "vertical_rate_mps": descent_rate,
                "on_ground": False,
                "squawk": "1200",
                "spi": False,
                "time_position_unix": base_time + i*10,
                "last_contact_unix": base_time + i*10 + 5
            }
        }
        flights.append(flight)
        altitude += descent_rate * 10  # Update altitude based on descent rate
    
    return flights


def test_anomaly_published_to_kafka(kafka_producer, kafka_consumer):
    """Test that anomalies are published to Kafka."""
    # Subscribe to anomalies topic
    kafka_consumer.subscribe([ANOMALIES_TOPIC])
    
    # Publish flight updates that should trigger anomaly
    test_icao24 = "anomaly_test_001"
    base_time = int(time.time())
    flight_updates = create_emergency_descent_flight(test_icao24, base_time)
    
    # Publish updates to flights.updates topic
    for flight in flight_updates:
        kafka_producer.produce(
            UPDATES_TOPIC,
            key=test_icao24,
            value=json.dumps(flight).encode('utf-8')
        )
    
    kafka_producer.poll(0)
    kafka_producer.flush(timeout=5)
    
    # Wait for anomaly to be detected and published
    anomaly_received = False
    start_time = time.time()
    
    while not anomaly_received and (time.time() - start_time) < TEST_TIMEOUT:
        msg = kafka_consumer.poll(timeout=2.0)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                continue
            else:
                pytest.fail(f"Consumer error: {msg.error()}")
        
        try:
            data = json.loads(msg.value().decode('utf-8'))
            if data.get("type") == "anomaly_event":
                payload = data.get("payload", {})
                if payload.get("icao24") == test_icao24:
                    anomaly_received = True
                    # Validate anomaly structure
                    assert payload.get("anomaly_type") in ["EMERGENCY_DESCENT", "SQUAWK_EMERGENCY"]
                    assert payload.get("severity") in ["LOW", "MEDIUM", "HIGH"]
                    assert "position" in payload
                    assert "details" in payload
        except Exception as e:
            pytest.fail(f"Failed to parse anomaly message: {e}")
    
    assert anomaly_received, f"Anomaly not detected within {TEST_TIMEOUT} seconds"


def test_anomaly_broadcast_via_websocket(kafka_producer):
    """Test that anomalies are broadcast via WebSocket."""
    client = WebSocketClient(BACKEND_WS_URL)
    
    try:
        client.connect()
        # Receive snapshot first
        client.receive_messages(count=1, timeout=5)
        
        # Publish flight updates that trigger anomaly
        test_icao24 = "anomaly_ws_test"
        base_time = int(time.time())
        flight_updates = create_emergency_descent_flight(test_icao24, base_time)
        
        for flight in flight_updates:
            kafka_producer.produce(
                UPDATES_TOPIC,
                key=test_icao24,
                value=json.dumps(flight).encode('utf-8')
            )
        
        kafka_producer.poll(0)
        kafka_producer.flush(timeout=5)
        
        # Wait for anomaly message via WebSocket
        anomaly_received = False
        start_time = time.time()
        
        while not anomaly_received and (time.time() - start_time) < TEST_TIMEOUT:
            messages = client.receive_messages(count=10, timeout=5)
            for msg in messages:
                if msg.get("type") == "anomaly":
                    payload = msg.get("payload", {})
                    if payload.get("icao24") == test_icao24:
                        anomaly_received = True
                        # Validate anomaly message structure
                        assert payload.get("anomaly_type") is not None
                        assert payload.get("severity") in ["LOW", "MEDIUM", "HIGH"]
                        assert "position" in payload
                        assert "details" in payload
                        break
            if anomaly_received:
                break
        
        assert anomaly_received, f"Anomaly not received via WebSocket within {TEST_TIMEOUT} seconds"
    finally:
        client.close()


def test_squawk_emergency_anomaly(kafka_producer, kafka_consumer):
    """Test that SQUAWK_7700 triggers anomaly detection."""
    kafka_consumer.subscribe([ANOMALIES_TOPIC])
    
    # Create flight with emergency squawk
    test_icao24 = "squawk_test_001"
    base_time = int(time.time())
    
    flight = {
        "schema_version": 1,
        "type": "flight_update",
        "produced_at": "2026-01-09T12:00:00.000Z",
        "source": {
            "provider": "opensky",
            "mode": "replay",
            "bbox": {"lat_min": 40.40, "lat_max": 41.20, "lon_min": -74.50, "lon_max": -73.50},
            "poll_interval_s": 10
        },
        "payload": {
            "icao24": test_icao24,
            "callsign": "EMERG",
            "position": {"lat": 40.6413, "lon": -73.7781},
            "altitude_m": 5000.0,
            "geo_altitude_m": 5100.0,
            "velocity_mps": 150.0,
            "heading_deg": 270.0,
            "vertical_rate_mps": 0.0,
            "on_ground": False,
            "squawk": "7700",  # Emergency code
            "spi": False,
            "time_position_unix": base_time,
            "last_contact_unix": base_time + 5
        }
    }
    
    kafka_producer.produce(
        UPDATES_TOPIC,
        key=test_icao24,
        value=json.dumps(flight).encode('utf-8')
    )
    kafka_producer.poll(0)
    kafka_producer.flush(timeout=5)
    
    # Wait for anomaly
    anomaly_received = False
    start_time = time.time()
    
    while not anomaly_received and (time.time() - start_time) < TEST_TIMEOUT:
        msg = kafka_consumer.poll(timeout=2.0)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                continue
            else:
                pytest.fail(f"Consumer error: {msg.error()}")
        
        try:
            data = json.loads(msg.value().decode('utf-8'))
            if data.get("type") == "anomaly_event":
                payload = data.get("payload", {})
                if payload.get("icao24") == test_icao24:
                    anomaly_received = True
                    assert payload.get("anomaly_type") == "SQUAWK_EMERGENCY"
                    assert payload.get("severity") == "HIGH"
        except Exception as e:
            pytest.fail(f"Failed to parse anomaly message: {e}")
    
    assert anomaly_received, f"SQUAWK_7700 anomaly not detected within {TEST_TIMEOUT} seconds"
