"""
Contract tests for producer service.

Validates that producer output matches schema contracts.
These tests run independently (no full stack required).
"""

import json
import pytest
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from contracts.validation import (
    validate_flight_state_envelope,
    validate_flight_update_envelope,
)


def load_example(filename: str) -> dict:
    """Load example JSON file."""
    example_path = Path(__file__).parent.parent.parent / "contracts" / "examples" / filename
    with open(example_path) as f:
        return json.load(f)


class TestProducerContract:
    """Test that producer output matches FlightStateEnvelope and FlightUpdateEnvelope schemas."""
    
    def test_flight_state_envelope_example_validates(self):
        """Test that example flight_state envelope validates."""
        example = load_example("flight_state_envelope.json")
        is_valid, envelope, error = validate_flight_state_envelope(example)
        
        assert is_valid, f"Example should validate: {error}"
        assert envelope is not None
        assert envelope.type == "flight_state"
        assert envelope.schema_version == 1
    
    def test_flight_update_envelope_example_validates(self):
        """Test that example flight_update envelope validates."""
        example = load_example("flight_update_envelope.json")
        is_valid, envelope, error = validate_flight_update_envelope(example)
        
        assert is_valid, f"Example should validate: {error}"
        assert envelope is not None
        assert envelope.type == "flight_update"
        assert envelope.schema_version == 1
    
    def test_flight_state_envelope_required_fields(self):
        """Test that missing required fields fail validation."""
        example = load_example("flight_state_envelope.json")
        
        # Remove required field
        del example["schema_version"]
        is_valid, _, error = validate_flight_state_envelope(example)
        assert not is_valid, "Should fail without schema_version"
    
    def test_flight_state_envelope_invalid_icao24(self):
        """Test that invalid icao24 format fails validation."""
        example = load_example("flight_state_envelope.json")
        
        # Invalid icao24 (uppercase, wrong length)
        example["payload"]["icao24"] = "A0B1C2D3"
        is_valid, _, error = validate_flight_state_envelope(example)
        assert not is_valid, "Should fail with invalid icao24 format"
    
    def test_flight_state_envelope_invalid_position(self):
        """Test that invalid position values fail validation."""
        example = load_example("flight_state_envelope.json")
        
        # Invalid latitude
        example["payload"]["position"]["lat"] = 91.0
        is_valid, _, error = validate_flight_state_envelope(example)
        assert not is_valid, "Should fail with invalid latitude"
        
        # Invalid longitude
        example = load_example("flight_state_envelope.json")
        example["payload"]["position"]["lon"] = -181.0
        is_valid, _, error = validate_flight_state_envelope(example)
        assert not is_valid, "Should fail with invalid longitude"
    
    def test_flight_state_envelope_invalid_heading(self):
        """Test that invalid heading values fail validation."""
        example = load_example("flight_state_envelope.json")
        
        # Heading >= 360
        example["payload"]["heading_deg"] = 360.0
        is_valid, _, error = validate_flight_state_envelope(example)
        assert not is_valid, "Should fail with heading >= 360"
        
        # Negative heading
        example["payload"]["heading_deg"] = -1.0
        is_valid, _, error = validate_flight_state_envelope(example)
        assert not is_valid, "Should fail with negative heading"
    
    def test_flight_state_envelope_nullable_fields(self):
        """Test that nullable fields can be null."""
        example = load_example("flight_state_envelope.json")
        
        # Set nullable fields to null
        example["payload"]["callsign"] = None
        example["payload"]["altitude_m"] = None
        example["payload"]["heading_deg"] = None
        
        is_valid, envelope, error = validate_flight_state_envelope(example)
        assert is_valid, f"Should allow null values: {error}"
        assert envelope.payload.callsign is None
        assert envelope.payload.altitude_m is None
        assert envelope.payload.heading_deg is None
