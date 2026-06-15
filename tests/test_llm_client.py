"""Unit tests for the LLMClient using mocked transport."""
import httpx
import pytest

from uia.utils.llm_client import LLMClient


@pytest.fixture
def anyio_backend():
    """Specify the backend for anyio tests."""
    return "asyncio"


@pytest.mark.anyio
async def test_well_formed_json_response():
    """Verify that a standard 200 response with raw JSON is successfully parsed."""
    def request_handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"founding_year": 1827, "name": "University of Toronto"}'
                    }
                }
            ]
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(request_handler)
    async with httpx.AsyncClient(transport=transport) as async_client:
        client = LLMClient(api_key="fake-key", client=async_client)
        result = await client.extract_structured(
            page_text="raw html content",
            target_schema_description="dict description",
            field_name="about",
            source_url="https://utoronto.ca",
        )
        assert result == {"founding_year": 1827, "name": "University of Toronto"}


@pytest.mark.anyio
async def test_markdown_fenced_json_response():
    """Verify that a response enclosed in markdown code fences is cleaned and parsed."""
    def request_handler(request: httpx.Request) -> httpx.Response:
        fenced_content = '```json\n{"founding_year": 1827, "name": "University of Toronto"}\n```'
        payload = {
            "choices": [
                {
                    "message": {
                        "content": fenced_content
                    }
                }
            ]
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(request_handler)
    async with httpx.AsyncClient(transport=transport) as async_client:
        client = LLMClient(api_key="fake-key", client=async_client)
        result = await client.extract_structured(
            page_text="raw html content",
            target_schema_description="dict description",
            field_name="about",
            source_url="https://utoronto.ca",
        )
        assert result == {"founding_year": 1827, "name": "University of Toronto"}


@pytest.mark.anyio
async def test_malformed_json_response_returns_empty_dict():
    """Verify that a completely invalid JSON response returns an empty dictionary gracefully."""
    def request_handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "This response contains no parseable JSON content at all."
                    }
                }
            ]
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(request_handler)
    async with httpx.AsyncClient(transport=transport) as async_client:
        client = LLMClient(api_key="fake-key", client=async_client)
        result = await client.extract_structured(
            page_text="raw html content",
            target_schema_description="dict description",
            field_name="about",
            source_url="https://utoronto.ca",
        )
        assert result == {}


@pytest.mark.anyio
async def test_429_rate_limit_retry_and_success():
    """Verify that 429 Rate Limit responses trigger retry rules and succeed on subsequent calls."""
    calls = []

    def request_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(429, text="Rate limit exceeded. Please try again.")

        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"success": true}'
                    }
                }
            ]
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(request_handler)
    async with httpx.AsyncClient(transport=transport) as async_client:
        client = LLMClient(api_key="fake-key", client=async_client)
        result = await client.extract_structured(
            page_text="raw html content",
            target_schema_description="dict description",
            field_name="about",
            source_url="https://utoronto.ca",
        )
        # Verify that we succeeded after retrying
        assert result == {"success": True}
        assert len(calls) == 3
