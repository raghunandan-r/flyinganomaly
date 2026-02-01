"""
Contract tests for backend service.

Validates that backend WebSocket messages match schema contracts.
These tests run independently (no full stack required).
"""

import json
import pytest
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from contracts.validation import (
    validate_snapshot_message,
    validate_delta_message,
    validate_anomaly_message,
)


def load_example(filename: str) -> dict:
    """Load example JSON file."""
    example_path = Path(__file__).parent.parent.parent / "contracts" / "examples" / filename
    with open(example_path) as f:
        return json.load(f)


class TestBackendContract:
    """Test that backend WebSocket messages match schemas."""
    
    def test_snapshot_message_example_validates(self):
        """Test that example snapshot message validates."""
        example = load_example("websocket_snapshot.json")
        is_valid, message, error = validate_snapshot_message(example)
        
        assert is_valid, f"Example should validate: {error}"
        assert message is not None
        assert message.type == "snapshot"
        assert len(message.flights) > 0
    
    def test_delta_message_example_validates(self):
        """Test that example delta message validates."""
        example = load_example("websocket_delta.json")
        is_valid, message, error = validate_delta_message(example)
        
        assert is_valid, f"Example should validate: {error}"
        assert message is not None
        assert message.type == "delta"
        assert isinstance(message.upserts, list)
        assert isinstance(message.removed, list)
    
    def test_anomaly_message_example_validates(self):
        """Test that example anomaly message validates."""
        example = load_example("websocket_anomaly.json")
        is_valid, message, error = validate_anomaly_message(example)
        
        assert is_valid, f"Example should validate: {error}"
        assert message is not None
        assert message.type == "anomaly"
        assert message.payload.anomaly_type in [
            "EMERGENCY_DESCENT",
            "GO_AROUND",
            "HOLDING",
            "LOW_ALTITUDE_WARNING",
            "SQUAWK_7700",
            "SQUAWK_7600",
            "SQUAWK_7500",
            "SQUAWK_EMERGENCY"
        ]
    
    def test_snapshot_message_missing_flights(self):
        """Test that snapshot without flights fails validation."""
        example = load_example("websocket_snapshot.json")
        del example["flights"]
        
        is_valid, _, error = validate_snapshot_message(example)
        assert not is_valid, "Should fail without flights array"
    
    def test_delta_message_invalid_removed_format(self):
        """Test that delta with invalid removed icao24 fails validation."""
        example = load_example("websocket_delta.json")
        example["removed"] = ["invalid_icao24", "123"]
        
        is_valid, _, error = validate_delta_message(example)
        assert not is_valid, "Should fail with invalid icao24 in removed list"
    
    def test_anomaly_message_invalid_severity(self):
        """Test that anomaly with invalid severity fails validation."""
        example = load_example("websocket_anomaly.json")
        example["payload"]["severity"] = "INVALID"
        
        is_valid, _, error = validate_anomaly_message(example)
        assert not is_valid, "Should fail with invalid severity"
    
    def test_snapshot_message_flight_status_values(self):
        """Test that flight status must be valid enum value."""
        example = load_example("websocket_snapshot.json")
        example["flights"][0]["status"] = "INVALID_STATUS"
        
        is_valid, _, error = validate_snapshot_message(example)
        assert not is_valid, "Should fail with invalid status value"
    
    def test_delta_message_empty_upserts_and_removed(self):
        """Test that delta can have empty upserts and removed arrays."""
        example = load_example("websocket_delta.json")
        example["upserts"] = []
        example["removed"] = []
        
        is_valid, message, error = validate_delta_message(example)
        assert is_valid, f"Should allow empty arrays: {error}"
        assert len(message.upserts) == 0
        assert len(message.removed) == 0
