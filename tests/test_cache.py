"""Unit and integration tests for the PageCache component and incremental runs."""
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from uia.agent.orchestrator import run_for_university
from uia.agent.planner import UniversityConfig
from uia.models.schema import ScrapedRecord, UniversityRecord, AboutInfo, LocationInfo
from uia.utils.cache import PageCache
from uia.utils.http_client import FetchResult


@pytest.fixture
def anyio_backend() -> str:
    """Specify the backend for anyio tests."""
    return "asyncio"


def test_page_cache_first_sight_and_second_call(tmp_path) -> None:
    """Tests that PageCache returns True on first sight, and False on subsequent calls if unchanged."""
    cache_file = tmp_path / "page_hashes.json"
    cache = PageCache(cache_path=str(cache_file))

    url = "https://example.com/about"
    text1 = "About this university. Located in Canada."
    text2 = "Updated about page text."

    # First sight should return True
    assert cache.has_changed(url, text1) is True

    # After update, it should return False for the same content
    cache.update(url, text1)
    assert cache.has_changed(url, text1) is False

    # Stored on disk should also load correctly
    new_cache = PageCache(cache_path=str(cache_file))
    assert new_cache.has_changed(url, text1) is False

    # Changing the text should return True
    assert new_cache.has_changed(url, text2) is True

    # Update new text and verify it doesn't report change anymore
    new_cache.update(url, text2)
    assert new_cache.has_changed(url, text2) is False


@pytest.mark.anyio
async def test_orchestrator_incremental_reuse(tmp_path) -> None:
    """Verifies that the orchestrator skips LLM extraction and reuses previous data when pages are unchanged."""
    cache_file = tmp_path / "page_hashes.json"
    cache = PageCache(cache_path=str(cache_file))

    # 1. Create a config with one category for simplicity
    config = UniversityConfig(
        name="Test University",
        country="Canada",
        base_url="https://test.edu",
        seed_urls={
            "about": ["https://test.edu/about"]
        }
    )

    # 2. Mock LLM client extract_structured response
    mock_llm = AsyncMock()
    mock_llm.extract_structured.return_value = {
        "name": "Test University",
        "location": {"city": "Toronto", "country": "Canada"},
        "institution_type": "public"
    }

    # 3. Setup mock FetchResult
    fetch_res = FetchResult(
        url="https://test.edu/about",
        status_code=200,
        html="<html><body>Clean Text V1</body></html>",
        fetched_at=datetime.now(timezone.utc),
        clean_text="Clean Text V1"
    )

    # Patch Crawler.fetch_plan to return our fetch_res
    with patch("uia.agent.crawler.Crawler.fetch_plan") as mock_fetch_plan:
        mock_fetch_plan.return_value = {"about": [fetch_res]}

        # --- RUN 1: Cache is empty, no previous record ---
        # LLM extraction should be called.
        record1 = await run_for_university(
            config,
            mock_llm,
            cache=cache,
            previous_record=None
        )

        assert mock_llm.extract_structured.call_count == 1
        assert record1.data.about.location.city == "Toronto"
        assert fetch_res.has_changed is True

        mock_llm.extract_structured.reset_mock()

        # --- RUN 2: Page content unchanged, previous record passed ---
        # LLM extraction should be skipped, reusing the previous record.
        # We simulate this by changing mock_llm's return value to verify it wasn't called.
        mock_llm.extract_structured.return_value = {
            "name": "Test University",
            "location": {"city": "Vancouver", "country": "Canada"},
            "institution_type": "public"
        }

        # The fetch_plan still returns the same page content
        fetch_res.has_changed = False  # will be computed by cache

        record2 = await run_for_university(
            config,
            mock_llm,
            cache=cache,
            previous_record=record1
        )

        # Extraction should NOT have been called
        assert mock_llm.extract_structured.call_count == 0
        # Reused location city should be "Toronto" from record1 (not Vancouver)
        assert record2.data.about.location.city == "Toronto"

        # --- RUN 3: Page content changed ---
        # LLM extraction should be called again.
        fetch_res_v2 = FetchResult(
            url="https://test.edu/about",
            status_code=200,
            html="<html><body>Clean Text V2 (Changed!)</body></html>",
            fetched_at=datetime.now(timezone.utc),
            clean_text="Clean Text V2 (Changed!)"
        )
        mock_fetch_plan.return_value = {"about": [fetch_res_v2]}

        record3 = await run_for_university(
            config,
            mock_llm,
            cache=cache,
            previous_record=record2
        )

        # Extraction SHOULD have been called
        assert mock_llm.extract_structured.call_count == 1
        # It should now use the new LLM output (Vancouver)
        assert record3.data.about.location.city == "Vancouver"
        assert fetch_res_v2.has_changed is True
