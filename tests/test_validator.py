"""Unit tests for the validator component in uia.agent.validator."""
import pytest
from datetime import datetime

from uia.agent.validator import validate
from uia.models.schema import (
    AboutInfo,
    AcceptanceRate,
    AverageSalary,
    CourseListing,
    GraduateEmployment,
    IntakeDeadline,
    LivingCosts,
    LocationInfo,
    Scholarship,
    TuitionFee,
    UniversityRecord,
    VisaPolicy,
)


@pytest.fixture
def clean_record() -> UniversityRecord:
    """Fixture returning a complete, valid, and clean UniversityRecord with plausible values."""
    about = AboutInfo(
        name="University of Toronto",
        founding_year=1827,
        location=LocationInfo(city="Toronto", country="Canada"),
        institution_type="public",
    )
    tuition = [
        TuitionFee(
            programme_level="undergraduate",
            domestic_fee=6590.0,
            international_fee=45000.0,
            currency="CAD",
            academic_year="2025/2026",
            source_url="https://future.utoronto.ca/finances/tuition-fees/",
        )
    ]
    living_costs = LivingCosts(
        city="Toronto",
        currency="CAD",
        monthly_rent=1500.0,
        monthly_food=400.0,
        monthly_transport=150.0,
        source_url="https://future.utoronto.ca/finances/financial-planning-calculator/",
    )
    scholarships = [
        Scholarship(
            name="Lester B. Pearson International Scholarship",
            value="Full tuition",
            eligibility_criteria="Outstanding academic achievement",
            application_deadline="2025-01-15",
            source_url="https://future.utoronto.ca/finances/scholarships/",
        )
    ]
    acceptance_rate = AcceptanceRate(
        overall_pct=43.0,
        undergraduate_pct=45.0,
        postgraduate_pct=40.0,
        year=2024,
        source_url="https://www.utoronto.ca/about-u-of-t/quickfacts",
    )
    graduate_employment = GraduateEmployment(
        employed_within_6_months_pct=90.0,
        data_source="Ontario Graduate Survey",
        data_year=2024,
        source_url="https://www.utoronto.ca/about-u-of-t/quickfacts",
    )
    average_salaries = [
        AverageSalary(
            field_of_study="Computer Science",
            median_salary=85000.0,
            currency="CAD",
            year=2024,
            source_url="https://www.utoronto.ca/about-u-of-t/quickfacts",
        )
    ]
    visa_policies = VisaPolicy(
        country="Canada",
        visa_type="Study Permit",
        key_requirements=["Letter of acceptance", "Proof of funds"],
        source_url="https://cie.utoronto.ca/",
    )
    intake_deadlines = [
        IntakeDeadline(
            intake_name="Fall 2025",
            programme_level="Undergraduate",
            application_open_date="2024-09-15",
            application_close_date="2025-01-15",
            source_url="https://future.utoronto.ca/apply/important-deadlines/",
        )
    ]
    course_listings = [
        CourseListing(
            code="CSC108",
            title="Introduction to Computer Programming",
            credits=0.5,
            description="Introduction to programming in Python.",
            prerequisites=[],
            mode="in-person",
            source_url="https://artsci.calendar.utoronto.ca/course/CSC108H1",
        )
    ]

    return UniversityRecord(
        about=about,
        tuition_fees=tuition,
        living_costs=living_costs,
        scholarships=scholarships,
        acceptance_rate=acceptance_rate,
        graduate_employment=graduate_employment,
        average_salaries=average_salaries,
        visa_policies=visa_policies,
        intake_deadlines=intake_deadlines,
        course_listings=course_listings,
    )


def test_clean_record_yields_full_confidence(clean_record):
    """Verify that a clean record yields no high/medium-severity flags and 1.0 confidence."""
    confidence, flags = validate(clean_record, country="Canada")
    
    # Check that there are no high or medium flags
    assert not any(f.severity in ("high", "medium") for f in flags)
    
    # Check that all fields have 1.0 confidence
    for field, score in confidence.items():
        assert score == 1.0, f"Field '{field}' did not have 1.0 confidence (got {score})"


def test_currency_cross_check_triggers_high_severity(clean_record):
    """Verify USD tuition/living costs/salaries for a Canadian university triggers high-severity flags."""
    # Modify tuition currency to USD
    clean_record.tuition_fees[0].currency = "USD"
    # Modify living costs currency to USD
    clean_record.living_costs.currency = "USD"
    # Modify average salaries currency to USD
    clean_record.average_salaries[0].currency = "USD"
    
    confidence, flags = validate(clean_record, country="Canada")
    
    # We expect high-severity flags for tuition_fees, living_costs, and average_salaries
    high_flags = [f for f in flags if f.severity == "high"]
    assert len(high_flags) >= 3
    
    fields_with_high_flags = {f.field for f in high_flags}
    assert "tuition_fees" in fields_with_high_flags
    assert "living_costs" in fields_with_high_flags
    assert "average_salaries" in fields_with_high_flags
    
    # Deductions should reduce confidence scores for these fields
    assert confidence["tuition_fees"] == 0.5  # 1.0 - 0.5 = 0.5
    assert confidence["living_costs"] == 0.5
    assert confidence["average_salaries"] == 0.5


def test_acceptance_rate_out_of_bounds_triggers_high_severity(clean_record):
    """Verify that an acceptance rate of 150% triggers high-severity flags."""
    clean_record.acceptance_rate.overall_pct = 150.0
    
    confidence, flags = validate(clean_record, country="Canada")
    
    high_flags = [f for f in flags if f.severity == "high" and f.field == "acceptance_rate"]
    assert len(high_flags) == 1
    assert "outside [0, 100]" in high_flags[0].issue
    
    # 1.0 - 0.5 = 0.5
    assert confidence["acceptance_rate"] == 0.5


def test_empty_listings_yields_base_confidence_point_three(clean_record):
    """Verify that empty course listings yields confidence 0.3 with a medium-severity flag."""
    clean_record.course_listings = []
    
    confidence, flags = validate(clean_record, country="Canada")
    
    # There should be a medium flag for course_listings
    matching_flags = [f for f in flags if f.field == "course_listings" and f.severity == "medium"]
    assert len(matching_flags) == 1
    assert "no data extracted" in matching_flags[0].issue
    
    # Empty field sets base confidence to 0.3, and deduction for medium flag is 0.25,
    # but wait: the rule says "If the field is entirely empty/None/empty list with no data extracted,
    # set its BASE confidence to 0.3 instead of 1.0. For every validation flag affecting that field,
    # deduct from its current value..."
    # Wait, does the "no data extracted" flag deduct from the 0.3 base confidence?
    # Yes, base_conf (0.3) - medium deduction (0.25) = 0.05.
    # Let's verify that the confidence is correctly computed as 0.05 (or clamped).
    assert confidence["course_listings"] == pytest.approx(0.05)


def test_international_fee_less_than_domestic_triggers_medium_severity(clean_record):
    """Verify that international fee < domestic fee triggers medium-severity flag."""
    clean_record.tuition_fees[0].international_fee = 5000.0
    clean_record.tuition_fees[0].domestic_fee = 6000.0
    
    confidence, flags = validate(clean_record, country="Canada")
    
    med_flags = [f for f in flags if f.severity == "medium" and f.field == "tuition_fees"]
    assert len(med_flags) == 1
    assert "is less than domestic fee" in med_flags[0].issue
    
    # 1.0 - 0.25 = 0.75
    assert confidence["tuition_fees"] == 0.75


def test_confidence_scores_clamping(clean_record):
    """Verify that multiple validation flags stack and correctly clamp to [0.0, 1.0]."""
    # Cause multiple high and medium severity flags on tuition_fees
    # 1. Currency mismatch (high: -0.5)
    # 2. Negative fee value (high: -0.5)
    # 3. International fee < domestic fee (medium: -0.25)
    clean_record.tuition_fees[0].currency = "USD"
    clean_record.tuition_fees[0].domestic_fee = -1000.0
    clean_record.tuition_fees[0].international_fee = -2000.0
    
    confidence, flags = validate(clean_record, country="Canada")
    
    # Total deduction: high (-0.5) * 3 [1 for currency, 2 for negative fees] + medium (-0.25) * 1 = 1.75
    # Base confidence = 1.0. Final should clamp to 0.0
    assert confidence["tuition_fees"] == 0.0
