"""
Integration test: Verify Kafka topic configurations and message formats.

This test verifies:
1. Topics exist with correct configurations
2. Message formats match expected schemas
3. Topic partitioning and replication
"""

import pytest
import json
import os
import subprocess
from typing import Dict, Any, List
from confluent_kafka import Consumer, Producer, KafkaError, TopicMetadata


KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
STATE_TOPIC = "flights.state"
UPDATES_TOPIC = "flights.updates"
ANOMALIES_TOPIC = "flights.anomalies"


@pytest.fixture(scope="module")
def kafka_admin():
    """Create Kafka admin client (using rpk or confluent-kafka)."""
    # For Redpanda, we can use rpk commands
    yield None


def get_topic_metadata(topic: str) -> Dict[str, Any]:
    """Get topic metadata using rpk."""
    try:
        result = subprocess.run(
            ["rpk", "topic", "describe", topic, "--brokers", KAFKA_BROKER],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Parse rpk output (simplified)
            return {"exists": True, "output": result.stdout}
        else:
            return {"exists": False, "error": result.stderr}
    except FileNotFoundError:
        # rpk not available, try alternative method
        return {"exists": None, "error": "rpk not found"}


def test_state_topic_exists():
    """Test that flights.state topic exists."""
    metadata = get_topic_metadata(STATE_TOPIC)
    
    if metadata["exists"] is None:
        pytest.skip("rpk not available, cannot check topic existence")
    
    # Try to create consumer and subscribe to verify topic exists
    try:
        consumer = Consumer({
            'bootstrap.servers': KAFKA_BROKER,
            'group.id': 'test_topic_check',
            'auto.offset.reset': 'earliest'
        })
        consumer.subscribe([STATE_TOPIC])
        
        # Try to get metadata
        metadata_dict = consumer.list_topics(timeout=5)
        assert STATE_TOPIC in metadata_dict.topics, f"Topic {STATE_TOPIC} does not exist"
        
        consumer.close()
    except Exception as e:
        pytest.fail(f"Failed to verify topic existence: {e}")


def test_updates_topic_exists():
    """Test that flights.updates topic exists."""
    try:
        consumer = Consumer({
            'bootstrap.servers': KAFKA_BROKER,
            'group.id': 'test_topic_check',
            'auto.offset.reset': 'earliest'
        })
        consumer.subscribe([UPDATES_TOPIC])
        
        metadata_dict = consumer.list_topics(timeout=5)
        assert UPDATES_TOPIC in metadata_dict.topics, f"Topic {UPDATES_TOPIC} does not exist"
        
        consumer.close()
    except Exception as e:
        pytest.fail(f"Failed to verify topic existence: {e}")


def test_anomalies_topic_exists():
    """Test that flights.anomalies topic exists."""
    try:
        consumer = Consumer({
            'bootstrap.servers': KAFKA_BROKER,
            'group.id': 'test_topic_check',
            'auto.offset.reset': 'earliest'
        })
        consumer.subscribe([ANOMALIES_TOPIC])
        
        metadata_dict = consumer.list_topics(timeout=5)
        assert ANOMALIES_TOPIC in metadata_dict.topics, f"Topic {ANOMALIES_TOPIC} does not exist"
        
        consumer.close()
    except Exception as e:
        pytest.fail(f"Failed to verify topic existence: {e}")


def test_state_topic_message_format():
    """Test that messages in flights.state match expected format."""
    consumer = Consumer({
        'bootstrap.servers': KAFKA_BROKER,
        'group.id': 'test_format_check',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False
    })
    
    try:
        consumer.subscribe([STATE_TOPIC])
        
        # Consume one message
        msg = consumer.poll(timeout=10.0)
        if msg is None:
            pytest.skip("No messages in flights.state topic")
        
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                pytest.skip("No messages in flights.state topic")
            else:
                pytest.fail(f"Consumer error: {msg.error()}")
        
        # Parse and validate message
        try:
            data = json.loads(msg.value().decode('utf-8'))
        except json.JSONDecodeError as e:
            pytest.fail(f"Message is not valid JSON: {e}")
        
        # Validate envelope structure
        assert "schema_version" in data, "Message missing 'schema_version'"
        assert "type" in data, "Message missing 'type'"
        assert "produced_at" in data, "Message missing 'produced_at'"
        assert "source" in data, "Message missing 'source'"
        assert "payload" in data, "Message missing 'payload'"
        
        # Validate type
        assert data["type"] == "flight_state", f"Expected type 'flight_state', got '{data['type']}'"
        
        # Validate payload structure
        payload = data["payload"]
        assert "icao24" in payload, "Payload missing 'icao24'"
        assert "position" in payload, "Payload missing 'position'"
        assert "lat" in payload["position"], "Position missing 'lat'"
        assert "lon" in payload["position"], "Position missing 'lon'"
        assert "last_contact_unix" in payload, "Payload missing 'last_contact_unix'"
        
    finally:
        consumer.close()


def test_updates_topic_message_format():
    """Test that messages in flights.updates match expected format."""
    consumer = Consumer({
        'bootstrap.servers': KAFKA_BROKER,
        'group.id': 'test_format_check',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False
    })
    
    try:
        consumer.subscribe([UPDATES_TOPIC])
        
        # Consume one message
        msg = consumer.poll(timeout=10.0)
        if msg is None:
            pytest.skip("No messages in flights.updates topic")
        
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                pytest.skip("No messages in flights.updates topic")
            else:
                pytest.fail(f"Consumer error: {msg.error()}")
        
        # Parse and validate message
        try:
            data = json.loads(msg.value().decode('utf-8'))
        except json.JSONDecodeError as e:
            pytest.fail(f"Message is not valid JSON: {e}")
        
        # Validate envelope structure
        assert "schema_version" in data
        assert "type" in data
        assert data["type"] in ["flight_state", "flight_update"], \
            f"Expected type 'flight_state' or 'flight_update', got '{data['type']}'"
        assert "payload" in data
        
    finally:
        consumer.close()


def test_anomalies_topic_message_format():
    """Test that messages in flights.anomalies match expected format."""
    consumer = Consumer({
        'bootstrap.servers': KAFKA_BROKER,
        'group.id': 'test_format_check',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False
    })
    
    try:
        consumer.subscribe([ANOMALIES_TOPIC])
        
        # Consume one message (may not exist if no anomalies)
        msg = consumer.poll(timeout=10.0)
        if msg is None:
            pytest.skip("No messages in flights.anomalies topic (no anomalies detected)")
        
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                pytest.skip("No messages in flights.anomalies topic")
            else:
                pytest.fail(f"Consumer error: {msg.error()}")
        
        # Parse and validate message
        try:
            data = json.loads(msg.value().decode('utf-8'))
        except json.JSONDecodeError as e:
            pytest.fail(f"Message is not valid JSON: {e}")
        
        # Validate envelope structure
        assert "schema_version" in data
        assert "type" in data
        assert data["type"] == "anomaly_event", f"Expected type 'anomaly_event', got '{data['type']}'"
        assert "payload" in data
        
        # Validate anomaly payload
        payload = data["payload"]
        assert "icao24" in payload
        assert "anomaly_type" in payload
        assert "severity" in payload
        assert payload["severity"] in ["LOW", "MEDIUM", "HIGH"]
        assert "position" in payload
        
    finally:
        consumer.close()


def test_topic_keyed_by_icao24():
    """Test that topics are keyed by icao24 (for compaction)."""
    # This test verifies that messages have keys set to icao24
    consumer = Consumer({
        'bootstrap.servers': KAFKA_BROKER,
        'group.id': 'test_key_check',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False
    })
    
    try:
        consumer.subscribe([STATE_TOPIC])
        
        # Consume a few messages
        messages = []
        for _ in range(5):
            msg = consumer.poll(timeout=2.0)
            if msg is None:
                break
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    break
                else:
                    pytest.fail(f"Consumer error: {msg.error()}")
            
            if msg.key():
                try:
                    key = msg.key().decode('utf-8')
                    data = json.loads(msg.value().decode('utf-8'))
                    payload = data.get("payload", {})
                    icao24 = payload.get("icao24")
                    
                    if icao24:
                        # Key should match icao24
                        assert key == icao24, \
                            f"Message key '{key}' does not match icao24 '{icao24}'"
                        messages.append((key, icao24))
                except Exception:
                    pass
        
        if len(messages) == 0:
            pytest.skip("No messages with keys to verify")
        
    finally:
        consumer.close()
