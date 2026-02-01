"""
Contract tests for processing service.

Validates that processing output matches schema contracts.
These tests run independently (no full stack required).
"""

import json
import pytest
from pathlib import Path
import sys
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from contracts.validation import validate_anomaly_event_envelope
from contracts.constants import (
    MESSAGE_TYPE_ANOMALY_EVENT,
    PROVIDER_SKYSENTINEL_PROCESSING,
    SCHEMA_VERSION,
)


def load_example(filename: str) -> dict:
    """Load example JSON file."""
    example_path = Path(__file__).parent.parent.parent / "contracts" / "examples" / filename
    with open(example_path) as f:
        return json.load(f)


class TestProcessingContract:
    """Test that processing output matches AnomalyEventEnvelope schema."""
    
    def test_anomaly_event_envelope_example_validates(self):
        """Test that example anomaly_event envelope validates."""
        example = load_example("anomaly_event_envelope.json")
        is_valid, envelope, error = validate_anomaly_event_envelope(example)
        
        assert is_valid, f"Example should validate: {error}"
        assert envelope is not None
        assert envelope.type == MESSAGE_TYPE_ANOMALY_EVENT
        assert envelope.schema_version == SCHEMA_VERSION
        assert envelope.source.provider == PROVIDER_SKYSENTINEL_PROCESSING
    
    def test_anomaly_event_envelope_required_fields(self):
        """Test that missing required fields fail validation."""
        example = load_example("anomaly_event_envelope.json")
        
        # Remove required field
        del example["payload"]["icao24"]
        is_valid, _, error = validate_anomaly_event_envelope(example)
        assert not is_valid, "Should fail without icao24"
    
    def test_anomaly_event_envelope_invalid_anomaly_type(self):
        """Test that invalid anomaly_type fails validation."""
        example = load_example("anomaly_event_envelope.json")
        
        example["payload"]["anomaly_type"] = "INVALID_TYPE"
        is_valid, _, error = validate_anomaly_event_envelope(example)
        assert not is_valid, "Should fail with invalid anomaly_type"
    
    def test_anomaly_event_envelope_invalid_severity(self):
        """Test that invalid severity fails validation."""
        example = load_example("anomaly_event_envelope.json")
        
        example["payload"]["severity"] = "INVALID"
        is_valid, _, error = validate_anomaly_event_envelope(example)
        assert not is_valid, "Should fail with invalid severity"
    
    def test_anomaly_event_envelope_valid_anomaly_types(self):
        """Test that all valid anomaly types are accepted."""
        valid_types = [
            "EMERGENCY_DESCENT",
            "GO_AROUND",
            "HOLDING",
            "LOW_ALTITUDE_WARNING",
            "SQUAWK_7700",
            "SQUAWK_7600",
            "SQUAWK_7500",
            "SQUAWK_EMERGENCY"
        ]
        
        example = load_example("anomaly_event_envelope.json")
        
        for anomaly_type in valid_types:
            example["payload"]["anomaly_type"] = anomaly_type
            is_valid, envelope, error = validate_anomaly_event_envelope(example)
            assert is_valid, f"Should accept {anomaly_type}: {error}"
            assert envelope.payload.anomaly_type == anomaly_type
    
    def test_anomaly_event_envelope_valid_severities(self):
        """Test that all valid severities are accepted."""
        valid_severities = ["LOW", "MEDIUM", "HIGH"]
        
        example = load_example("anomaly_event_envelope.json")
        
        for severity in valid_severities:
            example["payload"]["severity"] = severity
            is_valid, envelope, error = validate_anomaly_event_envelope(example)
            assert is_valid, f"Should accept {severity}: {error}"
            assert envelope.payload.severity == severity
    
    def test_anomaly_event_envelope_nullable_callsign(self):
        """Test that callsign can be null."""
        example = load_example("anomaly_event_envelope.json")
        example["payload"]["callsign"] = None
        
        is_valid, envelope, error = validate_anomaly_event_envelope(example)
        assert is_valid, f"Should allow null callsign: {error}"
        assert envelope.payload.callsign is None
    
    def test_anomaly_event_envelope_details_dict(self):
        """Test that details can contain arbitrary key-value pairs."""
        example = load_example("anomaly_event_envelope.json")
        example["payload"]["details"] = {
            "custom_field": "value",
            "numeric_field": 123,
            "nested": {"key": "value"}
        }
        
        is_valid, envelope, error = validate_anomaly_event_envelope(example)
        assert is_valid, f"Should allow arbitrary details: {error}"
        assert "custom_field" in envelope.payload.details
        assert envelope.payload.details["numeric_field"] == 123
    
    def test_anomaly_event_envelope_invalid_position(self):
        """Test that invalid position fails validation."""
        example = load_example("anomaly_event_envelope.json")
        
        # Invalid latitude
        example["payload"]["position"]["lat"] = 91.0
        is_valid, _, error = validate_anomaly_event_envelope(example)
        assert not is_valid, "Should fail with invalid latitude"
        
        # Invalid longitude
        example = load_example("anomaly_event_envelope.json")
        example["payload"]["position"]["lon"] = -181.0
        is_valid, _, error = validate_anomaly_event_envelope(example)
        assert not is_valid, "Should fail with invalid longitude"
