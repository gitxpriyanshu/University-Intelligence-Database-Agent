"""Unit tests for the ResilientHttpClient using mocked transport."""
import httpx
import pytest
from datetime import datetime, timezone

from uia.utils.http_client import ResilientHttpClient


@pytest.fixture
def anyio_backend():
    """Specify the backend for anyio tests."""
    return "asyncio"


@pytest.mark.anyio
async def test_successful_fetch():
    """Verify that a 200 OK response maps to a successful FetchResult with html populated."""
    def request_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        elif request.url.path == "/target":
            return httpx.Response(200, text="<html>Hello World</html>")
        return httpx.Response(404)

    transport = httpx.MockTransport(request_handler)
    async with httpx.AsyncClient(transport=transport) as async_client:
        client = ResilientHttpClient(
            base_domain="example.com",
            client=async_client,
            rate_limit_delay=0.01,
        )
        result = await client.fetch("https://example.com/target")

        assert result.url == "https://example.com/target"
        assert result.status_code == 200
        assert result.html == "<html>Hello World</html>"
        assert result.error is None
        assert isinstance(result.fetched_at, datetime)


@pytest.mark.anyio
async def test_robots_txt_disallow_blocks_network_call():
    """Verify that a disallowed robots.txt rule returns a blocked FetchResult and makes no HTTP call."""
    calls = []

    def request_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /blocked-path\nAllow: /")
        return httpx.Response(200, text="Should not be hit!")

    transport = httpx.MockTransport(request_handler)
    async with httpx.AsyncClient(transport=transport) as async_client:
        client = ResilientHttpClient(
            base_domain="example.com",
            client=async_client,
            rate_limit_delay=0.01,
        )
        # Fetch robots.txt first dynamically by checking/fetching
        result = await client.fetch("https://example.com/blocked-path")

        # Verify output matches blocked result
        assert result.status_code == 0
        assert result.html == ""
        assert result.error == "blocked_by_robots"

        # Verify only robots.txt was fetched, no network call to /blocked-path
        assert "/robots.txt" in calls
        assert "/blocked-path" not in calls


@pytest.mark.anyio
async def test_repeated_503_eventually_fails_gracefully():
    """Verify that repeated 503 errors trigger retries, then degrade gracefully to return an error."""
    calls = []

    def request_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(503, text="Service Temporarily Unavailable")

    transport = httpx.MockTransport(request_handler)
    async with httpx.AsyncClient(transport=transport) as async_client:
        # Construct client with low rate limit to speed up tests
        client = ResilientHttpClient(
            base_domain="example.com",
            client=async_client,
            rate_limit_delay=0.01,
        )
        result = await client.fetch("https://example.com/service")

        # Verify that we got a graceful degradation FetchResult
        assert result.status_code == 503
        assert result.html == "Service Temporarily Unavailable"
        assert result.error == "HTTP status error: 503"

        # Verify tenacity retries was triggered (1 initial call + 2 retries = 3 calls)
        # plus 1 call for robots.txt
        assert calls.count("/robots.txt") == 1
        assert calls.count("/service") == 3
