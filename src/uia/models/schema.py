"""Data schemas and Pydantic models for University Intelligence database records.

Defines the structure, type constraints, and documentation metadata for the 
10 intelligence fields and the top-level ScrapedRecord wrapper.
"""
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class RankingInfo(BaseModel):
    """Represents a ranking source and position for a university.

    Used to store official institutional ranking details.
    """
    rank: int = Field(..., description="The numeric ranking position (e.g. 21).")
    source: str = Field(..., description="The name of the ranking provider (e.g. QS, Times Higher Education).")
    year: int = Field(..., description="The year of the ranking publication.")


class LocationInfo(BaseModel):
    """Represents the geographical location of a university."""
    city: str = Field(..., description="City where the campus is located.")
    country: str = Field(..., description="Country where the campus is located.")


class AboutInfo(BaseModel):
    """Represents general overview information about a university."""
    name: str = Field(..., description="The official name of the university.")
    founding_year: Optional[int] = Field(None, description="The year the university was established.")
    overall_ranking: Optional[RankingInfo] = Field(None, description="The overall institutional ranking information.")
    location: LocationInfo = Field(..., description="The geographical location details.")
    institution_type: Literal["public", "private", "unknown"] = Field(
        ..., description="The status of the institution: public, private, or unknown."
    )


class TuitionFee(BaseModel):
    """Represents the tuition fee structure for a specific program level."""
    programme_level: str = Field(..., description="Level of study (e.g., undergraduate, postgraduate, phd).")
    domestic_fee: Optional[float] = Field(None, description="Annual tuition fee for domestic students.")
    international_fee: Optional[float] = Field(None, description="Annual tuition fee for international students.")
    currency: str = Field(..., description="Three-letter ISO 4217 currency code (e.g., CAD, AUD, USD).")
    academic_year: str = Field(..., description="The academic year associated with the fees (e.g., 2025/2026).")
    source_url: str = Field(..., description="Source URL where the fee data was located.")


class LivingCosts(BaseModel):
    """Represents the estimated living expenses in the university's city."""
    city: str = Field(..., description="The city name for the estimated costs.")
    monthly_rent: Optional[float] = Field(None, description="Estimated monthly rent/housing cost.")
    monthly_food: Optional[float] = Field(None, description="Estimated monthly food cost.")
    monthly_transport: Optional[float] = Field(None, description="Estimated monthly local transportation cost.")
    currency: str = Field(..., description="Three-letter ISO 4217 currency code.")
    source_url: str = Field(..., description="Source URL where the cost guidelines were published.")
    estimate_basis: Optional[str] = Field(None, description="Basis/metadata for the estimation (e.g., university cost estimator 2025).")


class Scholarship(BaseModel):
    """Represents a scholarship program offered by or for the university."""
    name: str = Field(..., description="Name of the scholarship.")
    value: Optional[str] = Field(None, description="The monetary value or benefits description (e.g., 'Full tuition', '$10,000').")
    eligibility_criteria: str = Field(..., description="Criteria required to be eligible for the scholarship.")
    application_deadline: Optional[str] = Field(None, description="Deadline for applications, either ISO format or seasonal description.")
    source_url: str = Field(..., description="Source URL where the scholarship details are published.")


class AcceptanceRate(BaseModel):
    """Represents the admission acceptance rates for the university."""
    overall_pct: Optional[float] = Field(None, description="Overall acceptance percentage (0.0 to 100.0).")
    undergraduate_pct: Optional[float] = Field(None, description="Undergraduate admission acceptance percentage.")
    postgraduate_pct: Optional[float] = Field(None, description="Postgraduate admission acceptance percentage.")
    year: Optional[int] = Field(None, description="The academic/reporting year of the data.")
    source_url: str = Field(..., description="Source URL where the rates were published.")


class GraduateEmployment(BaseModel):
    """Represents graduate employability statistics within 6 months of graduation."""
    employed_within_6_months_pct: Optional[float] = Field(None, description="Percentage of graduates employed within 6 months.")
    data_source: Optional[str] = Field(None, description="Source of the employment data survey or agency.")
    data_year: Optional[int] = Field(None, description="Year when the survey/statistics were collected.")
    source_url: str = Field(..., description="Source URL for the employment statistics.")


class AverageSalary(BaseModel):
    """Represents the average graduate starting salary by field of study."""
    field_of_study: str = Field(..., description="The academic field of study (e.g., Computer Science, Business).")
    median_salary: float = Field(..., description="Median or average annual starting salary.")
    currency: str = Field(..., description="Three-letter ISO 4217 currency code.")
    year: Optional[int] = Field(None, description="The year associated with the salary data.")
    source_url: str = Field(..., description="Source URL for the salary data.")


class VisaPolicy(BaseModel):
    """Represents visa policies and application requirements for international students."""
    country: str = Field(..., description="The host country for which the student visa is required.")
    visa_type: str = Field(..., description="The specific category or subclass of visa (e.g., Subclass 500 student visa).")
    processing_time: Optional[str] = Field(None, description="Typical or estimated processing time.")
    key_requirements: list[str] = Field(..., description="List of key requirements (e.g., health insurance, proof of funds).")
    source_url: str = Field(..., description="Source URL for official visa policy guidelines.")


class IntakeDeadline(BaseModel):
    """Represents key application deadlines for intake semesters."""
    intake_name: str = Field(..., description="The name of the semester or intake (e.g., Fall, Spring, Winter).")
    programme_level: Optional[str] = Field(None, description="The targeted program level (e.g., Undergraduate, Postgraduate).")
    application_open_date: Optional[str] = Field(None, description="Date when applications open.")
    application_close_date: Optional[str] = Field(None, description="Date when applications close.")
    source_url: str = Field(..., description="Source URL for academic calendar and deadlines.")


class CourseListing(BaseModel):
    """Represents details of a course/subject in the university catalog."""
    code: str = Field(..., description="Unique course identifier/code (e.g., CSC108).")
    title: str = Field(..., description="Full course title.")
    credits: Optional[float] = Field(None, description="Number of credit units.")
    description: Optional[str] = Field(None, description="Description of the course content.")
    prerequisites: list[str] = Field(..., description="Prerequisite courses required before taking this course.")
    mode: Optional[str] = Field(None, description="Mode of delivery (e.g., in-person, online, hybrid).")
    source_url: str = Field(..., description="Source URL of the course catalog page.")


class UniversityRecord(BaseModel):
    """A comprehensive database record containing all extracted intelligence categories for a university."""
    about: AboutInfo = Field(..., description="Overview and ranking details.")
    tuition_fees: list[TuitionFee] = Field(default_factory=list, description="List of tuition fee structures.")
    living_costs: LivingCosts = Field(..., description="Estimated cost of living expenses in the university's location.")
    scholarships: list[Scholarship] = Field(default_factory=list, description="Scholarships offered.")
    acceptance_rate: AcceptanceRate = Field(..., description="Acceptance rates details.")
    graduate_employment: GraduateEmployment = Field(..., description="Graduate employment rates statistics.")
    average_salaries: list[AverageSalary] = Field(default_factory=list, description="Average starting salaries by field.")
    visa_policies: VisaPolicy = Field(..., description="Student visa requirements and details.")
    intake_deadlines: list[IntakeDeadline] = Field(default_factory=list, description="Application timelines for program intakes.")
    course_listings: list[CourseListing] = Field(default_factory=list, description="A list of courses in the university catalog.")


class ValidationFlag(BaseModel):
    """Represents a potential issue or sanity check warning raised during data self-validation."""
    field: str = Field(..., description="The name of the validated field (e.g., 'tuition_fees', 'living_costs').")
    issue: str = Field(..., description="Explanation of why this field failed validation or is flagged.")
    severity: Literal["low", "medium", "high"] = Field(..., description="The impact/severity of the validation issue.")


class ScrapedRecord(BaseModel):
    """Top-level record wrapping the scraped university data, metadata, and validation checks."""
    university_name: str = Field(..., description="The common name of the university being scraped.")
    scraped_at: datetime = Field(..., description="Timestamp of when the scraping and compilation took place.")
    data: UniversityRecord = Field(..., description="The structured university intelligence database fields.")
    field_confidence: dict[str, float] = Field(
        ..., description="Confidence score from 0.0 to 1.0 mapping each top-level data category."
    )
    validation_flags: list[ValidationFlag] = Field(
        default_factory=list, description="List of issue flags raised during data self-validation."
    )
