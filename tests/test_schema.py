"""Unit tests for validation schemas in uia.models.schema."""
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from uia.models.schema import (
    AboutInfo,
    AcceptanceRate,
    GraduateEmployment,
    LivingCosts,
    LocationInfo,
    ScrapedRecord,
    UniversityRecord,
    VisaPolicy,
)


def test_minimal_scraped_record_serialization():
    """Verify that a minimal valid ScrapedRecord can be created and serialized to JSON."""
    about = AboutInfo(
        name="University of Toronto",
        founding_year=1827,
        location=LocationInfo(city="Toronto", country="Canada"),
        institution_type="public",
    )
    living_costs = LivingCosts(
        city="Toronto",
        currency="CAD",
        source_url="https://future.utoronto.ca/finances/financial-planning-calculator/",
    )
    acceptance_rate = AcceptanceRate(
        source_url="https://example.com",
    )
    graduate_employment = GraduateEmployment(
        source_url="https://example.com",
    )
    visa_policies = VisaPolicy(
        country="Canada",
        visa_type="Study Permit",
        key_requirements=["Letter of acceptance", "Proof of identity", "Proof of financial support"],
        source_url="https://example.com",
    )

    record = UniversityRecord(
        about=about,
        tuition_fees=[],
        living_costs=living_costs,
        scholarships=[],
        acceptance_rate=acceptance_rate,
        graduate_employment=graduate_employment,
        average_salaries=[],
        visa_policies=visa_policies,
        intake_deadlines=[],
        course_listings=[],
    )

    scraped = ScrapedRecord(
        university_name="University of Toronto",
        scraped_at=datetime.now(timezone.utc),
        data=record,
        field_confidence={"about": 1.0},
        validation_flags=[],
    )

    # Check serialization to dict and json
    serialized_dict = scraped.model_dump()
    assert serialized_dict["university_name"] == "University of Toronto"
    assert serialized_dict["data"]["about"]["institution_type"] == "public"

    serialized_json = scraped.model_dump_json()
    assert isinstance(serialized_json, str)
    assert "University of Toronto" in serialized_json


def test_invalid_institution_type_raises_error():
    """Verify that an invalid institution_type raises a Pydantic ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        AboutInfo(
            name="University of Toronto",
            founding_year=1827,
            location=LocationInfo(city="Toronto", country="Canada"),
            institution_type="invalid_type",  # Should be public, private, or unknown
        )
    assert "Input should be 'public', 'private' or 'unknown'" in str(exc_info.value)
