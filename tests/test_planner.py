"""Unit tests for the Planner using mocked transports and static HTML."""
import httpx
import pytest

from uia.agent.planner import Planner, UniversityConfig
from uia.utils.http_client import ResilientHttpClient


@pytest.fixture
def anyio_backend():
    """Specify the backend for anyio tests."""
    return "asyncio"


# HTML fixtures for testing planner heuristics
HTML_WITH_RELEVANT_LINKS = """
<html>
<body>
    <h1>Welcome to Toronto</h1>
    <a href="/tuition-fees-calculator">Check our Tuition Fees here</a>
    <a href="/scholarships-and-funding">Scholarship Opportunities</a>
    <a href="/external-link">External Link to Wikipedia</a>
</body>
</html>
"""

HTML_WITH_PAGINATION = """
<html>
<body>
    <h1>Course Directory</h1>
    <a href="/courses?page=2">Next page</a>
    <a href="/courses/math-101">Intro to Calculus</a>
</body>
</html>
"""

HTML_PAGE_2 = """
<html>
<body>
    <h1>Course Directory - Page 2</h1>
    <a href="/courses/science-200">Advanced Biology</a>
</body>
</html>
"""

HTML_NEAR_EMPTY = """
<html>
<head>
    <title>Dynamic University Portal</title>
    <script src="bundle.js"></script>
    <style>body { color: red; }</style>
</head>
<body>
    <div id="app"></div>
</body>
</html>
"""


@pytest.mark.anyio
async def test_planner_relevance_heuristics():
    """Verify that the planner discovers and prioritizes links based on keywords."""
    def request_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text=HTML_WITH_RELEVANT_LINKS)

    transport = httpx.MockTransport(request_handler)
    async with httpx.AsyncClient(transport=transport) as async_client:
        client = ResilientHttpClient(base_domain="utoronto.ca", client=async_client)
        planner = Planner(max_urls_per_category=4)
        config = UniversityConfig(
            name="University of Toronto",
            country="Canada",
            base_url="https://utoronto.ca",
            seed_urls={
                "tuition_fees": ["https://utoronto.ca/fees-home"],
                "scholarships": ["https://utoronto.ca/scholarships-home"],
            }
        )
        plan = await planner.build_plan(config, client)

        # Confirm tuition-related link was extracted
        tuition_urls = [t.url for t in plan.categories["tuition_fees"]]
        assert "https://utoronto.ca/fees-home" in tuition_urls
        assert "https://utoronto.ca/tuition-fees-calculator" in tuition_urls

        # Confirm scholarship-related link was extracted
        scholarship_urls = [t.url for t in plan.categories["scholarships"]]
        assert "https://utoronto.ca/scholarships-home" in scholarship_urls
        assert "https://utoronto.ca/scholarships-and-funding" in scholarship_urls


@pytest.mark.anyio
async def test_planner_follows_pagination():
    """Verify that pagination anchors are detected, enqueued, and evaluated."""
    def request_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        elif request.url.path == "/courses-home":
            return httpx.Response(200, text=HTML_WITH_PAGINATION)
        elif request.url.path == "/courses" and request.url.query == b"page=2":
            return httpx.Response(200, text=HTML_PAGE_2)
        return httpx.Response(404)

    transport = httpx.MockTransport(request_handler)
    async with httpx.AsyncClient(transport=transport) as async_client:
        client = ResilientHttpClient(base_domain="utoronto.ca", client=async_client)
        # Configure planner to follow up to 3 pages
        planner = Planner(max_urls_per_category=4, max_pages_per_category=3)
        config = UniversityConfig(
            name="University of Toronto",
            country="Canada",
            base_url="https://utoronto.ca",
            seed_urls={
                "course_listings": ["https://utoronto.ca/courses-home"],
            }
        )
        plan = await planner.build_plan(config, client)
        urls = [t.url for t in plan.categories["course_listings"]]

        # Verify initial seed
        assert "https://utoronto.ca/courses-home" in urls
        # Verify next page was enqueued and fetched
        assert "https://utoronto.ca/courses?page=2" in urls
        # Verify relevant links on both pages were extracted
        assert "https://utoronto.ca/courses/math-101" in urls
        assert "https://utoronto.ca/courses/science-200" in urls


@pytest.mark.anyio
async def test_planner_js_detection_flags_needs_render():
    """Verify that dynamic client-side shell pages with minimal text trigger needs_render."""
    def request_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text=HTML_NEAR_EMPTY)

    transport = httpx.MockTransport(request_handler)
    async with httpx.AsyncClient(transport=transport) as async_client:
        client = ResilientHttpClient(base_domain="utoronto.ca", client=async_client)
        planner = Planner(max_urls_per_category=4)
        config = UniversityConfig(
            name="University of Toronto",
            country="Canada",
            base_url="https://utoronto.ca",
            seed_urls={
                "about": ["https://utoronto.ca/portal-home"],
            }
        )
        plan = await planner.build_plan(config, client)
        targets = plan.categories["about"]

        assert len(targets) == 1
        assert targets[0].url == "https://utoronto.ca/portal-home"
        assert targets[0].needs_render is True
