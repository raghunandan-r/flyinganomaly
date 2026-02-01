"""
Integration test: Verify WebSocket protocol (snapshot/delta/anomaly messages).

This test verifies:
1. Snapshot message format and content
2. Delta message format and merging logic
3. Anomaly message format
4. Message sequence numbers
5. Message timestamps
"""

import pytest
import json
import time
import os
from typing import List, Dict, Any
import websocket


BACKEND_WS_URL = os.getenv("BACKEND_WS_URL", "ws://localhost:8000/ws/flights")
TEST_TIMEOUT = 30  # seconds


class WebSocketClient:
    """WebSocket client for protocol testing."""
    
    def __init__(self, url: str):
        self.url = url
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


def test_snapshot_message_format():
    """Test snapshot message format."""
    client = WebSocketClient(BACKEND_WS_URL)
    
    try:
        client.connect()
        messages = client.receive_messages(count=1, timeout=5)
        
        assert len(messages) > 0, "No snapshot message received"
        
        snapshot = messages[0]
        assert snapshot.get("type") == "snapshot", f"Expected type 'snapshot', got '{snapshot.get('type')}'"
        
        # Validate required fields
        assert "timestamp" in snapshot, "Snapshot missing 'timestamp' field"
        assert "sequence" in snapshot, "Snapshot missing 'sequence' field"
        assert "flights" in snapshot, "Snapshot missing 'flights' field"
        
        # Validate timestamp format (ISO 8601)
        timestamp = snapshot["timestamp"]
        from datetime import datetime
        try:
            datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except ValueError:
            pytest.fail(f"Invalid timestamp format: {timestamp}")
        
        # Validate sequence number
        assert isinstance(snapshot["sequence"], int), "Sequence must be integer"
        assert snapshot["sequence"] >= 0, "Sequence must be non-negative"
        
        # Validate flights array
        assert isinstance(snapshot["flights"], list), "Flights must be a list"
        
        # Validate flight structure if flights exist
        if len(snapshot["flights"]) > 0:
            flight = snapshot["flights"][0]
            assert "icao24" in flight, "Flight missing 'icao24' field"
            assert "position" in flight, "Flight missing 'position' field"
            assert "lat" in flight["position"], "Position missing 'lat' field"
            assert "lon" in flight["position"], "Position missing 'lon' field"
    finally:
        client.close()


def test_delta_message_format():
    """Test delta message format."""
    client = WebSocketClient(BACKEND_WS_URL)
    
    try:
        client.connect()
        # Receive snapshot first
        client.receive_messages(count=1, timeout=5)
        
        # Wait for delta messages
        messages = client.receive_messages(count=5, timeout=15)
        delta_messages = [m for m in messages if m.get("type") == "delta"]
        
        assert len(delta_messages) > 0, "No delta messages received"
        
        delta = delta_messages[0]
        assert delta.get("type") == "delta"
        
        # Validate required fields
        assert "timestamp" in delta, "Delta missing 'timestamp' field"
        assert "sequence" in delta, "Delta missing 'sequence' field"
        assert "upserts" in delta, "Delta missing 'upserts' field"
        assert "removed" in delta, "Delta missing 'removed' field"
        
        # Validate types
        assert isinstance(delta["upserts"], list), "Upserts must be a list"
        assert isinstance(delta["removed"], list), "Removed must be a list"
        
        # Validate timestamp format
        timestamp = delta["timestamp"]
        from datetime import datetime
        try:
            datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except ValueError:
            pytest.fail(f"Invalid timestamp format: {timestamp}")
        
        # Validate sequence number
        assert isinstance(delta["sequence"], int), "Sequence must be integer"
        
        # Validate flight structure in upserts if present
        if len(delta["upserts"]) > 0:
            flight = delta["upserts"][0]
            assert "icao24" in flight, "Upsert flight missing 'icao24' field"
            assert "position" in flight, "Upsert flight missing 'position' field"
        
        # Validate removed list contains strings (icao24 values)
        for removed_icao24 in delta["removed"]:
            assert isinstance(removed_icao24, str), "Removed items must be strings (icao24)"
    finally:
        client.close()


def test_anomaly_message_format():
    """Test anomaly message format."""
    client = WebSocketClient(BACKEND_WS_URL)
    
    try:
        client.connect()
        # Receive snapshot first
        client.receive_messages(count=1, timeout=5)
        
        # Wait for anomaly messages (may not be present if no anomalies)
        messages = client.receive_messages(count=20, timeout=10)
        anomaly_messages = [m for m in messages if m.get("type") == "anomaly"]
        
        # If no anomalies, that's okay - just validate structure if present
        if len(anomaly_messages) > 0:
            anomaly = anomaly_messages[0]
            assert anomaly.get("type") == "anomaly"
            
            # Validate required fields
            assert "timestamp" in anomaly, "Anomaly missing 'timestamp' field"
            assert "payload" in anomaly, "Anomaly missing 'payload' field"
            
            payload = anomaly["payload"]
            assert "icao24" in payload, "Anomaly payload missing 'icao24' field"
            assert "anomaly_type" in payload, "Anomaly payload missing 'anomaly_type' field"
            assert "severity" in payload, "Anomaly payload missing 'severity' field"
            assert "position" in payload, "Anomaly payload missing 'position' field"
            assert "details" in payload, "Anomaly payload missing 'details' field"
            
            # Validate severity enum
            assert payload["severity"] in ["LOW", "MEDIUM", "HIGH"], \
                f"Invalid severity: {payload['severity']}"
            
            # Validate position structure
            position = payload["position"]
            assert "lat" in position, "Anomaly position missing 'lat' field"
            assert "lon" in position, "Anomaly position missing 'lon' field"
    finally:
        client.close()


def test_message_sequence_numbers():
    """Test that message sequence numbers are monotonic."""
    client = WebSocketClient(BACKEND_WS_URL)
    
    try:
        client.connect()
        messages = client.receive_messages(count=10, timeout=20)
        
        sequences = []
        for msg in messages:
            if "sequence" in msg:
                sequences.append((msg.get("type"), msg["sequence"]))
        
        if len(sequences) < 2:
            pytest.skip("Not enough messages with sequence numbers")
        
        # Check that sequences are non-decreasing
        for i in range(1, len(sequences)):
            prev_seq = sequences[i-1][1]
            curr_seq = sequences[i][1]
            assert curr_seq >= prev_seq, \
                f"Sequence number decreased: {sequences[i-1]} -> {sequences[i]}"
    finally:
        client.close()


def test_message_timestamps():
    """Test that message timestamps are valid and reasonable."""
    client = WebSocketClient(BACKEND_WS_URL)
    
    try:
        client.connect()
        messages = client.receive_messages(count=10, timeout=20)
        
        from datetime import datetime, timezone
        
        for msg in messages:
            if "timestamp" in msg:
                timestamp_str = msg["timestamp"]
                try:
                    dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    # Check timestamp is recent (within last hour)
                    now = datetime.now(timezone.utc)
                    time_diff = abs((now - dt).total_seconds())
                    assert time_diff < 3600, \
                        f"Timestamp too old: {timestamp_str} (diff: {time_diff}s)"
                except ValueError as e:
                    pytest.fail(f"Invalid timestamp format: {timestamp_str} - {e}")
    finally:
        client.close()


def test_snapshot_contains_all_flights():
    """Test that snapshot contains all current flights."""
    client1 = WebSocketClient(BACKEND_WS_URL)
    client2 = WebSocketClient(BACKEND_WS_URL)
    
    try:
        # Connect two clients
        client1.connect()
        client2.connect()
        
        # Get snapshots from both
        snapshot1 = client1.receive_messages(count=1, timeout=5)[0]
        snapshot2 = client2.receive_messages(count=1, timeout=5)[0]
        
        # Both should have same flights (or very similar, allowing for timing)
        assert snapshot1.get("type") == "snapshot"
        assert snapshot2.get("type") == "snapshot"
        
        flights1 = {f["icao24"] for f in snapshot1.get("flights", [])}
        flights2 = {f["icao24"] for f in snapshot2.get("flights", [])}
        
        # Allow some difference due to timing, but should be mostly the same
        # If both snapshots are empty, that's also valid
        if len(flights1) > 0 or len(flights2) > 0:
            # At least some overlap expected
            overlap = len(flights1 & flights2)
            total = len(flights1 | flights2)
            if total > 0:
                overlap_ratio = overlap / total
                assert overlap_ratio > 0.5, \
                    f"Snapshots too different: {overlap}/{total} overlap"
    finally:
        client1.close()
        client2.close()
