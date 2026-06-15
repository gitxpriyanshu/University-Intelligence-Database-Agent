"""Orchestrator run loop driving the scraping agent execution for a single university.

Provides run_for_university which coordinates the Planner, ResilientHttpClient,
Crawler (with browser rendering fallback), and LLMClient to compile the full
structured UniversityRecord.
"""
import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from pydantic import TypeAdapter

from uia.agent.crawler import Crawler
from uia.agent.planner import Planner, UniversityConfig
from uia.models.schema import (
    AboutInfo,
    AcceptanceRate,
    AverageSalary,
    CourseListing,
    GraduateEmployment,
    IntakeDeadline,
    LivingCosts,
    LocationInfo,
    RankingInfo,
    Scholarship,
    ScrapedRecord,
    TuitionFee,
    UniversityRecord,
    ValidationFlag,
    VisaPolicy,
)
from uia.utils.http_client import ResilientHttpClient
from uia.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

# Type mappings for each of the 10 University Intelligence database fields.
# Lists are wrapped so TypeAdapter generates list schemas programmatically.
TYPE_MAP: Dict[str, Any] = {
    "about": AboutInfo,
    "tuition_fees": List[TuitionFee],
    "living_costs": LivingCosts,
    "scholarships": List[Scholarship],
    "acceptance_rate": AcceptanceRate,
    "graduate_employment": GraduateEmployment,
    "average_salaries": List[AverageSalary],
    "visa_policies": VisaPolicy,
    "intake_deadlines": List[IntakeDeadline],
    "course_listings": List[CourseListing],
}


def _get_default_for_type(target_type: Any, config: UniversityConfig) -> Any:
    """Helper to instantiate default empty records when extraction yields no data.

    Ensures that the output contains all 10 fields, satisfying structural criteria.
    """
    origin = getattr(target_type, "__origin__", None)
    if origin is list or target_type is list:
        return []

    # Handle single sub-models by populating required schema fields with placeholders
    if target_type is AboutInfo:
        return AboutInfo(
            name=config.name,
            location=LocationInfo(city="Unknown", country=config.country),
            institution_type="unknown",
        )
    elif target_type is LivingCosts:
        return LivingCosts(
            city="Unknown",
            currency="USD",
            source_url=config.base_url,
        )
    elif target_type is AcceptanceRate:
        return AcceptanceRate(
            source_url=config.base_url,
        )
    elif target_type is GraduateEmployment:
        return GraduateEmployment(
            source_url=config.base_url,
        )
    elif target_type is VisaPolicy:
        return VisaPolicy(
            country=config.country,
            visa_type="Unknown",
            key_requirements=[],
            source_url=config.base_url,
        )

    return None


def placeholder_validate(record: UniversityRecord) -> Tuple[Dict[str, float], List[ValidationFlag]]:
    """Placeholder validator function.

    To be implemented fully in the next prompt. Currently returns full confidence
    and empty validation flags.
    """
    confidence: Dict[str, float] = {}
    for field in record.model_fields:
        confidence[field] = 1.0
    return confidence, []


async def run_for_university(config: UniversityConfig, llm_client: LLMClient) -> ScrapedRecord:
    """Orchestrates the scraping, crawling, and AI-extraction loop for a single university.

    Guarantees top-level fault tolerance so that execution errors in one university
    target do not crash runs for other universities.

    Args:
        config: The target university config parameters and seed paths.
        llm_client: The active Groq client interface for structured extraction.

    Returns:
        A ScrapedRecord containing the compiled intelligence, confidence metrics, and flags.
    """
    scraped_at = datetime.now(timezone.utc)
    http_client = None

    try:
        logger.info(f"Starting pipeline orchestration for university: {config.name}")

        # 1. Instantiate the resilient HTTP client for target domain
        http_client = ResilientHttpClient(base_domain=config.base_url)

        # 2. Build the CrawlPlan (Planning Loop)
        planner = Planner()
        plan = await planner.build_plan(config, http_client)

        # 3. Execute fetching of target URLs (Crawl Execution & JS rendering)
        crawler = Crawler()
        crawl_results = await crawler.fetch_plan(plan, http_client)

        # 4. Perform structured AI extraction across the 10 data categories
        extracted_data: Dict[str, Any] = {}

        for category, target_type in TYPE_MAP.items():
            results = crawl_results.get(category, [])
            clean_texts = [res.clean_text for res in results if res and not res.error and res.clean_text]
            combined_text = "\n\n".join(clean_texts)

            if not combined_text.strip():
                logger.warning(
                    f"[{config.name}] No text crawled successfully for '{category}'. "
                    "Applying empty placeholders."
                )
                extracted_data[category] = _get_default_for_type(target_type, config)
                continue

            # Programmatically generate JSON schema representation of the expected target type
            adapter = TypeAdapter(target_type)
            schema_description = json.dumps(adapter.json_schema(), indent=2)

            # Extract source URLs for tracking metadata
            source_urls = ", ".join([res.url for res in results if res]) or config.base_url

            logger.info(f"[{config.name}] Extracting fields for category '{category}'")
            extracted_dict = await llm_client.extract_structured(
                page_text=combined_text,
                target_schema_description=schema_description,
                field_name=category,
                source_url=source_urls,
            )

            # Validate and load dictionary results into schema classes
            try:
                if not extracted_dict:
                    logger.warning(f"[{config.name}] Empty extraction return for category '{category}'")
                    extracted_data[category] = _get_default_for_type(target_type, config)
                else:
                    validated = adapter.validate_python(extracted_dict)
                    extracted_data[category] = validated
            except Exception as eval_err:
                logger.warning(
                    f"[{config.name}] Extraction validation failed for '{category}': {eval_err}. "
                    "Defaulting to empty placeholders."
                )
                extracted_data[category] = _get_default_for_type(target_type, config)

        # 5. Compile the UniversityRecord
        record = UniversityRecord(**extracted_data)

        # 6. Apply Validator (currently placeholder)
        confidence, validation_flags = placeholder_validate(record)

        return ScrapedRecord(
            university_name=config.name,
            scraped_at=scraped_at,
            data=record,
            field_confidence=confidence,
            validation_flags=validation_flags,
        )

    except Exception as fatal_err:
        logger.error(
            f"Fatal orchestration error for '{config.name}': {fatal_err}\n"
            f"{traceback.format_exc()}"
        )

        # Top-level Graceful Degradation: return empty fallback record with error flag
        fallback_about = AboutInfo(
            name=config.name,
            location=LocationInfo(city="Unknown", country=config.country),
            institution_type="unknown",
        )
        fallback_record = UniversityRecord(
            about=fallback_about,
            tuition_fees=[],
            living_costs=LivingCosts(city="Unknown", currency="USD", source_url=config.base_url),
            scholarships=[],
            acceptance_rate=AcceptanceRate(source_url=config.base_url),
            graduate_employment=GraduateEmployment(source_url=config.base_url),
            average_salaries=[],
            visa_policies=VisaPolicy(
                country=config.country, visa_type="Unknown", key_requirements=[], source_url=config.base_url
            ),
            intake_deadlines=[],
            course_listings=[],
        )

        failure_flag = ValidationFlag(
            field="orchestrator",
            issue=f"Fatal orchestrator pipeline failure: {str(fatal_err)}",
            severity="high",
        )

        confidence = {f: 0.0 for f in fallback_record.model_fields}

        return ScrapedRecord(
            university_name=config.name,
            scraped_at=scraped_at,
            data=fallback_record,
            field_confidence=confidence,
            validation_flags=[failure_flag],
        )

    finally:
        # Enforce HTTP connection cleanup
        if http_client:
            await http_client.close()
