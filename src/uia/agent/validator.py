"""Self-validation stage for scraped university database records.

Provides rules to detect missing, malformed, or implausible values,
verify cross-field constraints, and calculate field-level confidence scores.
"""
import logging
from datetime import datetime
from typing import Dict, List, Tuple

from uia.models.schema import (
    UniversityRecord,
    ValidationFlag,
)

logger = logging.getLogger(__name__)

# Expected currency per country dictionary. Can be extended as needed.
COUNTRY_CURRENCIES: Dict[str, str] = {
    "United States": "USD",
    "United Kingdom": "GBP",
    "Canada": "CAD",
    "Australia": "AUD",
    "Germany": "EUR",
    "France": "EUR",
    "Japan": "JPY",
    "New Zealand": "NZD",
    "Singapore": "SGD",
}


def _parse_date(date_str: str) -> bool:
    """Helper to parse a date string against common formats.

    Returns True if successfully parsed, False otherwise.
    """
    if not date_str:
        return False
    
    # Clean string
    cleaned = date_str.strip()
    
    # Try standard ISO / datetime parsing
    try:
        datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        return True
    except ValueError:
        pass
    
    # Common formats to test
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
        "%B %d, %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%d %b %Y",
    ]
    for fmt in formats:
        try:
            datetime.strptime(cleaned, fmt)
            return True
        except ValueError:
            pass
            
    return False


def _get_parsed_date(date_str: str) -> datetime | None:
    """Parses a date string and returns the datetime object if valid, else None."""
    if not date_str:
        return None
    cleaned = date_str.strip()
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        pass
        
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
        "%B %d, %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%d %b %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            pass
    return None


def validate(record: UniversityRecord, country: str) -> Tuple[Dict[str, float], List[ValidationFlag]]:
    """Validates the scraped UniversityRecord and returns confidence scores and flags.

    Checks:
    - Missing fields (empty/None/empty list)
    - Currency matching target country
    - Percentage range and sanity checks
    - Date validity and logical order
    - Numeric plausibility of fees, salaries, founding year
    - Living costs bounds
    - Visa policies and course listings completeness

    Args:
        record: The compiled university intelligence data.
        country: The target university country name.

    Returns:
        A tuple of (field confidence scores dict, list of ValidationFlag instances).
    """
    flags: List[ValidationFlag] = []
    
    # Determine base emptiness for each top-level field
    empty_fields: Dict[str, bool] = {}
    
    # 1. Check about field
    # It must exist, but we check if the values inside are empty placeholders
    about_empty = (
        not record.about
        or not record.about.name
        or record.about.name == "Unknown"
        or (record.about.founding_year is None and record.about.overall_ranking is None and record.about.institution_type == "unknown")
    )
    empty_fields["about"] = about_empty
    
    # 2. Check tuition_fees
    empty_fields["tuition_fees"] = not record.tuition_fees
    
    # 3. Check living_costs
    # Considered empty if monthly rent, food, and transport are all missing/None
    living_empty = (
        not record.living_costs
        or (record.living_costs.monthly_rent is None
            and record.living_costs.monthly_food is None
            and record.living_costs.monthly_transport is None)
    )
    empty_fields["living_costs"] = living_empty
    
    # 4. Check scholarships
    empty_fields["scholarships"] = not record.scholarships
    
    # 5. Check acceptance_rate
    acceptance_empty = (
        not record.acceptance_rate
        or (record.acceptance_rate.overall_pct is None
            and record.acceptance_rate.undergraduate_pct is None
            and record.acceptance_rate.postgraduate_pct is None)
    )
    empty_fields["acceptance_rate"] = acceptance_empty
    
    # 6. Check graduate_employment
    employment_empty = (
        not record.graduate_employment
        or record.graduate_employment.employed_within_6_months_pct is None
    )
    empty_fields["graduate_employment"] = employment_empty
    
    # 7. Check average_salaries
    empty_fields["average_salaries"] = not record.average_salaries
    
    # 8. Check visa_policies
    visa_empty = (
        not record.visa_policies
        or (record.visa_policies.visa_type in ("Unknown", "", None)
            and not record.visa_policies.key_requirements)
    )
    empty_fields["visa_policies"] = visa_empty
    
    # 9. Check intake_deadlines
    empty_fields["intake_deadlines"] = not record.intake_deadlines
    
    # 10. Check course_listings
    empty_fields["course_listings"] = not record.course_listings

    # Add missing-value flags for each empty category
    for field_name, is_empty in empty_fields.items():
        if is_empty:
            flags.append(
                ValidationFlag(
                    field=field_name,
                    issue="no data extracted",
                    severity="medium",
                )
            )

    # Expected currency mapping
    expected_currency = COUNTRY_CURRENCIES.get(country)

    # ----------------------------------------------------
    # Category-specific Validation Rules
    # ----------------------------------------------------

    # ABOUT
    if not empty_fields["about"] and record.about:
        # Founding year check
        current_year = datetime.now().year
        f_year = record.about.founding_year
        if f_year is not None:
            if f_year < 1000 or f_year > current_year:
                flags.append(
                    ValidationFlag(
                        field="about",
                        issue=f"Implausible founding year: {f_year}",
                        severity="medium",
                    )
                )
        
        # Institution type
        if record.about.institution_type == "unknown":
            flags.append(
                ValidationFlag(
                    field="about",
                    issue="Institution type is unknown",
                    severity="low",
                )
            )

    # TUITION FEES
    if not empty_fields["tuition_fees"]:
        for idx, fee in enumerate(record.tuition_fees):
            # Currency check
            if expected_currency and fee.currency:
                if fee.currency.strip().upper() != expected_currency.upper():
                    flags.append(
                        ValidationFlag(
                            field="tuition_fees",
                            issue=f"Tuition fee currency mismatch: expected {expected_currency}, got {fee.currency} for entry {idx}",
                            severity="high",
                        )
                    )
            
            # Non-negative and generous ceiling check
            if fee.domestic_fee is not None:
                if fee.domestic_fee < 0:
                    flags.append(
                        ValidationFlag(
                            field="tuition_fees",
                            issue=f"Negative domestic fee: {fee.domestic_fee} for entry {idx}",
                            severity="high",
                        )
                    )
                elif fee.domestic_fee > 500000:
                    flags.append(
                        ValidationFlag(
                            field="tuition_fees",
                            issue=f"Domestic fee is an outlier (> 500,000): {fee.domestic_fee} for entry {idx}",
                            severity="medium",
                        )
                    )
                    
            if fee.international_fee is not None:
                if fee.international_fee < 0:
                    flags.append(
                        ValidationFlag(
                            field="tuition_fees",
                            issue=f"Negative international fee: {fee.international_fee} for entry {idx}",
                            severity="high",
                        )
                    )
                elif fee.international_fee > 500000:
                    flags.append(
                        ValidationFlag(
                            field="tuition_fees",
                            issue=f"International fee is an outlier (> 500,000): {fee.international_fee} for entry {idx}",
                            severity="medium",
                        )
                    )

            # Cross-fee check: international vs domestic
            if fee.international_fee is not None and fee.domestic_fee is not None:
                if fee.international_fee < fee.domestic_fee:
                    flags.append(
                        ValidationFlag(
                            field="tuition_fees",
                            issue=f"International fee ({fee.international_fee}) is less than domestic fee ({fee.domestic_fee}) for entry {idx}",
                            severity="medium",
                        )
                    )

    # LIVING COSTS
    if not empty_fields["living_costs"] and record.living_costs:
        # Currency check
        if expected_currency and record.living_costs.currency:
            if record.living_costs.currency.strip().upper() != expected_currency.upper():
                flags.append(
                    ValidationFlag(
                        field="living_costs",
                        issue=f"Living costs currency mismatch: expected {expected_currency}, got {record.living_costs.currency}",
                        severity="high",
                    )
                )

        # Non-negative checks
        rent = record.living_costs.monthly_rent
        food = record.living_costs.monthly_food
        transport = record.living_costs.monthly_transport
        
        for cost_name, cost_val in [("rent", rent), ("food", food), ("transport", transport)]:
            if cost_val is not None:
                if cost_val < 0:
                    flags.append(
                        ValidationFlag(
                            field="living_costs",
                            issue=f"Negative monthly {cost_name} cost: {cost_val}",
                            severity="high",
                        )
                    )
        
        # Monthly rent ceiling sanity check
        if rent is not None and rent > 10000:
            flags.append(
                ValidationFlag(
                    field="living_costs",
                    issue=f"Monthly rent is exceptionally high (> 10,000): {rent}",
                    severity="medium",
                )
            )

    # SCHOLARSHIPS
    if not empty_fields["scholarships"]:
        for idx, scholarship in enumerate(record.scholarships):
            # Application deadline date parsing check
            if scholarship.application_deadline:
                # Some deadlines are descriptive (e.g. "Rolling", "Fall 2025"), so check if it contains numbers
                # before flagging as a bad date format. If it has a date-like structure but is malformed, we flag it.
                # However, if it parses as string descriptive, it might not be a date. 
                # Let's attempt to parse if it contains digits or common date patterns.
                has_digit = any(char.isdigit() for char in scholarship.application_deadline)
                if has_digit:
                    if not _parse_date(scholarship.application_deadline):
                        flags.append(
                            ValidationFlag(
                                field="scholarships",
                                issue=f"Malformed application deadline: '{scholarship.application_deadline}' for entry {idx}",
                                severity="medium",
                            )
                        )

    # ACCEPTANCE RATE
    if not empty_fields["acceptance_rate"] and record.acceptance_rate:
        ar = record.acceptance_rate
        for rate_name, rate_val in [
            ("overall_pct", ar.overall_pct),
            ("undergraduate_pct", ar.undergraduate_pct),
            ("postgraduate_pct", ar.postgraduate_pct),
        ]:
            if rate_val is not None:
                if rate_val < 0 or rate_val > 100:
                    flags.append(
                        ValidationFlag(
                            field="acceptance_rate",
                            issue=f"Acceptance rate {rate_name} is outside [0, 100] range: {rate_val}%",
                            severity="high",
                        )
                    )
                elif rate_val == 0 or rate_val == 100:
                    flags.append(
                        ValidationFlag(
                            field="acceptance_rate",
                            issue=f"Acceptance rate {rate_name} is exactly {rate_val}% (potential parsing anomaly)",
                            severity="low",
                        )
                    )

    # GRADUATE EMPLOYMENT
    if not empty_fields["graduate_employment"] and record.graduate_employment:
        emp_pct = record.graduate_employment.employed_within_6_months_pct
        if emp_pct is not None:
            if emp_pct < 0 or emp_pct > 100:
                flags.append(
                    ValidationFlag(
                        field="graduate_employment",
                        issue=f"Graduate employment percentage is outside [0, 100] range: {emp_pct}%",
                        severity="high",
                    )
                )
            elif emp_pct == 0 or emp_pct == 100:
                flags.append(
                    ValidationFlag(
                        field="graduate_employment",
                        issue=f"Graduate employment percentage is exactly {emp_pct}% (potential parsing anomaly)",
                        severity="low",
                    )
                )

    # AVERAGE SALARIES
    if not empty_fields["average_salaries"]:
        for idx, sal in enumerate(record.average_salaries):
            # Currency check
            if expected_currency and sal.currency:
                if sal.currency.strip().upper() != expected_currency.upper():
                    flags.append(
                        ValidationFlag(
                            field="average_salaries",
                            issue=f"Average salary currency mismatch: expected {expected_currency}, got {sal.currency} for entry {idx}",
                            severity="high",
                        )
                    )
            
            # Median salary sanity
            if sal.median_salary < 0:
                flags.append(
                    ValidationFlag(
                        field="average_salaries",
                        issue=f"Negative median salary: {sal.median_salary} for entry {idx}",
                        severity="high",
                    )
                )
            elif sal.median_salary > 500000:
                flags.append(
                    ValidationFlag(
                        field="average_salaries",
                        issue=f"Median salary is an outlier (> 500,000): {sal.median_salary} for entry {idx}",
                        severity="medium",
                    )
                )

    # VISA POLICIES
    if not empty_fields["visa_policies"] and record.visa_policies:
        visa = record.visa_policies
        if not visa.visa_type or visa.visa_type == "Unknown":
            flags.append(
                ValidationFlag(
                    field="visa_policies",
                    issue="Visa type is missing or set to 'Unknown'",
                    severity="medium",
                )
            )
        if not visa.key_requirements:
            flags.append(
                ValidationFlag(
                    field="visa_policies",
                    issue="Key requirements list is empty",
                    severity="low",
                )
            )

    # INTAKE DEADLINES
    if not empty_fields["intake_deadlines"]:
        for idx, deadline in enumerate(record.intake_deadlines):
            open_parsed = _get_parsed_date(deadline.application_open_date)
            close_parsed = _get_parsed_date(deadline.application_close_date)
            
            # Check open date structure if not empty
            if deadline.application_open_date and not open_parsed:
                # Check if it has numbers
                if any(char.isdigit() for char in deadline.application_open_date):
                    flags.append(
                        ValidationFlag(
                            field="intake_deadlines",
                            issue=f"Malformed application open date: '{deadline.application_open_date}' for entry {idx}",
                            severity="medium",
                        )
                    )
                    
            # Check close date structure if not empty
            if deadline.application_close_date and not close_parsed:
                if any(char.isdigit() for char in deadline.application_close_date):
                    flags.append(
                        ValidationFlag(
                            field="intake_deadlines",
                            issue=f"Malformed application close date: '{deadline.application_close_date}' for entry {idx}",
                            severity="medium",
                        )
                    )

            # Check sequence order
            if open_parsed and close_parsed:
                if close_parsed < open_parsed:
                    flags.append(
                        ValidationFlag(
                            field="intake_deadlines",
                            issue=f"Application close date ({deadline.application_close_date}) is before open date ({deadline.application_open_date}) for entry {idx}",
                            severity="medium",
                        )
                    )

    # COURSE LISTINGS
    if not empty_fields["course_listings"]:
        for idx, course in enumerate(record.course_listings):
            if not course.code or not course.title:
                flags.append(
                    ValidationFlag(
                        field="course_listings",
                        issue=f"Course code or title is missing for entry {idx} (Code: '{course.code}', Title: '{course.title}')",
                        severity="low",
                    )
                )

    # ----------------------------------------------------
    # Confidence Scoring Compilation
    # ----------------------------------------------------
    confidence_scores: Dict[str, float] = {}

    for field_name in record.__class__.model_fields:
        # Base confidence
        if empty_fields.get(field_name, False):
            base_conf = 0.3
        else:
            base_conf = 1.0
            
        # Deduct per flag targeting this field
        deductions = 0.0
        for flag in flags:
            if flag.field == field_name:
                if flag.severity == "high":
                    deductions += 0.5
                elif flag.severity == "medium":
                    deductions += 0.25
                elif flag.severity == "low":
                    deductions += 0.1
                    
        final_conf = base_conf - deductions
        # Clamp to [0.0, 1.0]
        confidence_scores[field_name] = max(0.0, min(1.0, final_conf))

    return confidence_scores, flags
