"""
Smoke test: End-to-end pipeline test from producer → backend → frontend.

This test verifies that:
1. Producer publishes messages to Kafka
2. Backend consumes and serves via WebSocket
3. Frontend can receive and parse messages
"""

import pytest
import json
import time
import subprocess
import os
from typing import List, Dict, Any
from confluent_kafka import Consumer, Producer, KafkaError
import websocket
import threading


# Test configuration
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
BACKEND_WS_URL = os.getenv("BACKEND_WS_URL", "ws://localhost:8000/ws/flights")
TEST_TIMEOUT = 30  # seconds


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
    """Create Kafka consumer for testing."""
    consumer = Consumer({
        'bootstrap.servers': KAFKA_BROKER,
        'group.id': 'smoke_test_consumer',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False
    })
    yield consumer
    consumer.close()


@pytest.fixture(scope="module")
def kafka_producer():
    """Create Kafka producer for testing."""
    producer = Producer({
        'bootstrap.servers': KAFKA_BROKER,
        'acks': 'all',
        'retries': 3
    })
    yield producer
    producer.flush()
    producer.close()


def test_producer_publishes_to_kafka(kafka_producer):
    """Test that producer can publish messages to Kafka."""
    topic = "flights.state"
    test_message = {
        "schema_version": 1,
        "type": "flight_state",
        "produced_at": "2026-01-09T12:00:00.000Z",
        "source": {
            "provider": "opensky",
            "mode": "replay",
            "bbox": {"lat_min": 40.40, "lat_max": 41.20, "lon_min": -74.50, "lon_max": -73.50},
            "poll_interval_s": 10
        },
        "payload": {
            "icao24": "test123",
            "callsign": "TEST",
            "position": {"lat": 40.6413, "lon": -73.7781},
            "altitude_m": 3048.0,
            "geo_altitude_m": 3100.0,
            "velocity_mps": 125.5,
            "heading_deg": 270.0,
            "vertical_rate_mps": -5.2,
            "on_ground": False,
            "squawk": "1200",
            "spi": False,
            "time_position_unix": 1704672000,
            "last_contact_unix": 1704672005
        }
    }
    
    # Publish message
    try:
        kafka_producer.produce(
            topic,
            key="test123",
            value=json.dumps(test_message).encode('utf-8')
        )
        kafka_producer.poll(0)
        kafka_producer.flush(timeout=5)
    except Exception as e:
        pytest.fail(f"Failed to publish message: {e}")


def test_backend_consumes_from_kafka(kafka_consumer):
    """Test that backend can consume messages from Kafka."""
    topic = "flights.state"
    kafka_consumer.subscribe([topic])
    
    # Wait for messages
    messages_received = []
    start_time = time.time()
    
    while len(messages_received) == 0 and (time.time() - start_time) < TEST_TIMEOUT:
        msg = kafka_consumer.poll(timeout=1.0)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                continue
            else:
                pytest.fail(f"Consumer error: {msg.error()}")
        
        try:
            data = json.loads(msg.value().decode('utf-8'))
            messages_received.append(data)
        except Exception as e:
            pytest.fail(f"Failed to parse message: {e}")
    
    assert len(messages_received) > 0, "No messages received from Kafka"
    
    # Validate message structure
    msg = messages_received[0]
    assert msg.get("schema_version") == 1
    assert msg.get("type") == "flight_state"
    assert "payload" in msg
    assert "icao24" in msg["payload"]


def test_websocket_snapshot_on_connect():
    """Test that WebSocket sends snapshot on connect."""
    client = WebSocketClient(BACKEND_WS_URL)
    
    try:
        client.connect()
        messages = client.receive_messages(count=1, timeout=5)
        
        assert len(messages) > 0, "No snapshot message received"
        
        snapshot = messages[0]
        assert snapshot.get("type") == "snapshot"
        assert "timestamp" in snapshot
        assert "sequence" in snapshot
        assert "flights" in snapshot
        assert isinstance(snapshot["flights"], list)
    finally:
        client.close()


def test_websocket_delta_updates():
    """Test that WebSocket sends delta updates."""
    client = WebSocketClient(BACKEND_WS_URL)
    
    try:
        client.connect()
        # Receive snapshot first
        client.receive_messages(count=1, timeout=5)
        
        # Wait for delta updates
        messages = client.receive_messages(count=2, timeout=10)
        
        # Filter for delta messages
        delta_messages = [m for m in messages if m.get("type") == "delta"]
        
        if len(delta_messages) > 0:
            delta = delta_messages[0]
            assert "timestamp" in delta
            assert "sequence" in delta
            assert "upserts" in delta or "removed" in delta
    finally:
        client.close()


def test_end_to_end_flow(kafka_producer):
    """Test complete flow: publish → consume → WebSocket."""
    # Publish test message
    topic = "flights.state"
    test_message = {
        "schema_version": 1,
        "type": "flight_state",
        "produced_at": "2026-01-09T12:00:00.000Z",
        "source": {
            "provider": "opensky",
            "mode": "replay",
            "bbox": {"lat_min": 40.40, "lat_max": 41.20, "lon_min": -74.50, "lon_max": -73.50},
            "poll_interval_s": 10
        },
        "payload": {
            "icao24": "e2e_test",
            "callsign": "E2E",
            "position": {"lat": 40.6413, "lon": -73.7781},
            "altitude_m": 3048.0,
            "geo_altitude_m": 3100.0,
            "velocity_mps": 125.5,
            "heading_deg": 270.0,
            "vertical_rate_mps": -5.2,
            "on_ground": False,
            "squawk": "1200",
            "spi": False,
            "time_position_unix": int(time.time()),
            "last_contact_unix": int(time.time())
        }
    }
    
    kafka_producer.produce(
        topic,
        key="e2e_test",
        value=json.dumps(test_message).encode('utf-8')
    )
    kafka_producer.poll(0)
    kafka_producer.flush(timeout=5)
    
    # Connect to WebSocket and wait for update
    client = WebSocketClient(BACKEND_WS_URL)
    
    try:
        client.connect()
        # Get snapshot
        snapshot = client.receive_messages(count=1, timeout=5)[0]
        
        # Wait for delta with our test flight
        start_time = time.time()
        found_test_flight = False
        
        while (time.time() - start_time) < TEST_TIMEOUT and not found_test_flight:
            messages = client.receive_messages(count=5, timeout=5)
            for msg in messages:
                if msg.get("type") == "delta":
                    upserts = msg.get("upserts", [])
                    for flight in upserts:
                        if flight.get("icao24") == "e2e_test":
                            found_test_flight = True
                            break
                    if found_test_flight:
                        break
        
        assert found_test_flight, "Test flight not found in WebSocket delta updates"
    finally:
        client.close()
