"""Unit tests for the FastAPI query server."""
import os
import json
import pytest
from fastapi.testclient import TestClient

from uia.api.server import app
from uia.models.schema import ScrapedRecord, UniversityRecord, AboutInfo, LocationInfo
from datetime import datetime, timezone


@pytest.fixture
def test_client() -> TestClient:
    """Fixture to provide a FastAPI TestClient."""
    return TestClient(app)


@pytest.fixture
def mock_output_json(tmp_path, monkeypatch):
    """Fixture to mock the database JSON file read in server.py."""
    output_file = tmp_path / "universities.json"
    
    # Mock data mirroring universities.json structure
    data = [
        {
            "university_name": "Test University",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "data": {
                "about": {
                    "name": "Test University",
                    "founding_year": 1999,
                    "location": {"city": "New York", "country": "United States"},
                    "institution_type": "private"
                },
                "tuition_fees": [],
                "living_costs": {
                    "city": "New York",
                    "currency": "USD",
                    "source_url": "https://test.edu"
                },
                "scholarships": [],
                "acceptance_rate": {"source_url": "https://test.edu"},
                "graduate_employment": {"source_url": "https://test.edu"},
                "average_salaries": [],
                "visa_policies": {
                    "country": "United States",
                    "visa_type": "F-1",
                    "key_requirements": ["I-20"],
                    "source_url": "https://test.edu"
                },
                "intake_deadlines": [],
                "course_listings": []
            },
            "field_confidence": {
                "about": 0.8,
                "living_costs": 0.5
            },
            "validation_flags": [
                {
                    "field": "living_costs",
                    "issue": "no rent parsed",
                    "severity": "low"
                }
            ]
        }
    ]
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
        
    # Monkeypatch the _load_records method in server.py to read from our test file
    def mock_load(json_path=None):
        with open(output_file, "r", encoding="utf-8") as f:
            return json.load(f)
            
    monkeypatch.setattr("uia.api.server._load_records", mock_load)
    return output_file


def test_list_universities(test_client, mock_output_json) -> None:
    """Verify GET /universities returns the correct list of names."""
    response = test_client.get("/universities")
    assert response.status_code == 200
    assert response.json() == ["Test University"]


def test_get_university_success(test_client, mock_output_json) -> None:
    """Verify GET /universities/{name} returns the full record."""
    response = test_client.get("/universities/Test%20University")
    assert response.status_code == 200
    data = response.json()
    assert data["university_name"] == "Test University"
    assert data["data"]["about"]["founding_year"] == 1999


def test_get_university_not_found(test_client, mock_output_json) -> None:
    """Verify GET /universities/{name} returns 404 for missing university."""
    response = test_client.get("/universities/Unknown%20Uni")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_university_field_success(test_client, mock_output_json) -> None:
    """Verify GET /universities/{name}/{field} returns correct field structure."""
    response = test_client.get("/universities/test%20university/about")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["field"] == "about"
    assert res_data["value"]["founding_year"] == 1999
    assert res_data["confidence"] == 0.8
    assert res_data["validation_flags"] == []

    # Query field with validation flags
    response_flags = test_client.get("/universities/test%20university/living_costs")
    assert response_flags.status_code == 200
    res_flags = response_flags.json()
    assert res_flags["field"] == "living_costs"
    assert len(res_flags["validation_flags"]) == 1
    assert res_flags["validation_flags"][0]["severity"] == "low"


def test_get_university_field_not_found(test_client, mock_output_json) -> None:
    """Verify GET /universities/{name}/{field} returns 404 for invalid fields."""
    response = test_client.get("/universities/test%20university/invalid_field_name")
    assert response.status_code == 404
    assert "field" in response.json()["detail"].lower()
