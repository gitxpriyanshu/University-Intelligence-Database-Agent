"""FastAPI query server for University Intelligence database records.

Provides GET endpoints to query scraped university data, individual field details,
confidence scores, and validation flags.
"""

import json
import os
from typing import Any, Dict, List
from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel

from uia.models.schema import ScrapedRecord, ValidationFlag

app = FastAPI(
    title="University Intelligence Database Agent API",
    description="Query interface for structured academic intelligence scraped records.",
    version="0.1.0",
)


def _load_records(json_path: str = "data/output/universities.json") -> List[Dict[str, Any]]:
    """Loads raw records from the outputs JSON file if it exists."""
    if not os.path.exists(json_path):
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


class FieldDetailResponse(BaseModel):
    """API response model for a single field query."""
    field: str
    value: Any
    confidence: float
    validation_flags: List[ValidationFlag]


@app.get("/universities", response_model=List[str])
def list_universities() -> List[str]:
    """Retrieves a list of all scraped university names available in the database."""
    records = _load_records()
    return [r["university_name"] for r in records if "university_name" in r]


@app.get("/universities/{name}", response_model=Dict[str, Any])
def get_university(
    name: str = Path(..., description="The name of the university to query (case-insensitive).")
) -> Dict[str, Any]:
    """Retrieves the full ScrapedRecord for a specific university."""
    records = _load_records()
    for r in records:
        if r.get("university_name", "").lower() == name.lower():
            # Return raw dictionary directly (conforms to ScrapedRecord schema)
            return r
    raise HTTPException(status_code=404, detail=f"University '{name}' not found in database.")


@app.get("/universities/{name}/{field}", response_model=FieldDetailResponse)
def get_university_field(
    name: str = Path(..., description="The name of the university to query (case-insensitive)."),
    field: str = Path(..., description="The top-level field name to retrieve.")
) -> FieldDetailResponse:
    """Retrieves a single top-level field value, confidence score, and validation flags."""
    records = _load_records()
    target_record = None
    for r in records:
        if r.get("university_name", "").lower() == name.lower():
            target_record = r
            break

    if not target_record:
        raise HTTPException(status_code=404, detail=f"University '{name}' not found.")

    data = target_record.get("data", {})
    if field not in data:
        raise HTTPException(
            status_code=404,
            detail=f"Field '{field}' not found. Supported fields are: {list(data.keys())}"
        )

    # Extract confidence score and flags for the specific field
    confidence = target_record.get("field_confidence", {}).get(field, 0.0)
    flags = [
        f for f in target_record.get("validation_flags", [])
        if f.get("field") == field
    ]

    # Map flags back to ValidationFlag Pydantic models for validation response
    typed_flags = []
    for f in flags:
        try:
            typed_flags.append(ValidationFlag(**f))
        except Exception:
            pass

    return FieldDetailResponse(
        field=field,
        value=data[field],
        confidence=confidence,
        validation_flags=typed_flags,
    )
