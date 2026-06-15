"""Resilient HTTP client for university web scraping.

Provides a ResilientHttpClient that wraps httpx.AsyncClient with features for
respecting robots.txt, rate limiting, retrying on failure, and graceful degradation.
"""
import asyncio
import logging
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import urlparse

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Holds the result of a single HTTP fetch operation.

    Designed to support graceful degradation by carrying error metadata
    rather than raising exceptions up the call stack.
    """
    url: str
    status_code: int
    html: str
    fetched_at: datetime
    error: Optional[str] = None
    clean_text: str = ""


class HttpResponseError(Exception):
    """Raised when an HTTP response returns a 5xx error status.

    Used internally to trigger tenacity retries on server-side failures.
    """
    def __init__(self, response: httpx.Response):
        self.response = response
        super().__init__(f"HTTP response error: {response.status_code}")


class ResilientHttpClient:
    """A highly resilient HTTP client designed for respectful and robust web scraping.

    Resilience Strategies:
    1. Compliance: Reads and respects robots.txt permissions before fetching.
    2. Rate Limiting: Enforces a configurable delay between consecutive requests
       to the same host, avoiding server overload.
    3. Retries: Uses the tenacity library to retry requests on transport errors
       or 5xx responses using exponential backoff (up to 3 attempts).
    4. Graceful Degradation: Captures all terminal errors and returns a FetchResult
       object with the error details instead of raising exceptions, allowing the
       caller to handle partial scraping results.
    """

    def __init__(
        self,
        base_domain: str,
        rate_limit_delay: float = 2.0,
        timeout: float = 10.0,
        user_agent: str = "UniversityIntelAgent/1.0 (+contact email placeholder)",
        client: Optional[httpx.AsyncClient] = None,
    ):
        """Initializes the ResilientHttpClient.

        Args:
            base_domain: The domain or base URL representing the scraping target.
            rate_limit_delay: Minimum delay in seconds between calls to the same host.
            timeout: Timeout in seconds for HTTP requests.
            user_agent: The User-Agent string sent in headers.
            client: Optional pre-configured httpx.AsyncClient (mainly for testing).
        """
        # Ensure base_domain has a scheme, default to https
        if not base_domain.startswith(("http://", "https://")):
            self.base_url = f"https://{base_domain}"
        else:
            self.base_url = base_domain

        parsed = urlparse(self.base_url)
        self.base_domain = parsed.netloc or parsed.path

        self.rate_limit_delay = rate_limit_delay
        self.timeout = timeout
        self.user_agent = user_agent

        # Configure httpx.AsyncClient
        headers = {"User-Agent": self.user_agent}
        self.client = client or httpx.AsyncClient(timeout=self.timeout, headers=headers)

        # Robots.txt initialization
        self.robots_parser = urllib.robotparser.RobotFileParser()
        self.robots_url = f"{parsed.scheme or 'https'}://{self.base_domain}/robots.txt"
        self._robots_fetched = False

        # State tracking for rate limiting
        self._host_locks: Dict[str, asyncio.Lock] = {}
        self._last_request_time: Dict[str, float] = {}
        self._robots_lock = asyncio.Lock()

    def can_fetch(self, url: str) -> bool:
        """Checks if a URL can be crawled according to the parsed robots.txt rules.

        Args:
            url: The target URL to check.

        Returns:
            True if fetching is allowed, False otherwise.
        """
        return self.robots_parser.can_fetch(self.user_agent, url)

    async def _ensure_robots_fetched(self):
        """Asynchronously fetches and parses the robots.txt file for the base domain.

        Runs once before the first fetch operation. Fallbacks to allowing all if
        fetching fails.
        """
        if self._robots_fetched:
            return

        async with self._robots_lock:
            if self._robots_fetched:
                return

            logger.info(f"Fetching robots.txt from {self.robots_url}")
            try:
                # Direct get request avoiding rate limiting lock and retry wrappers
                response = await self.client.get(self.robots_url)
                if response.status_code == 200:
                    self.robots_parser.parse(response.text.splitlines())
                    logger.info("Successfully parsed robots.txt rules.")
                else:
                    logger.warning(
                        f"Failed to fetch robots.txt (status: {response.status_code}). Defaulting to allow all."
                    )
                    self.robots_parser.parse([])
            except Exception as e:
                logger.warning(f"Error fetching robots.txt: {e}. Defaulting to allow all.")
                self.robots_parser.parse([])

            self._robots_fetched = True

    def _get_host_lock(self, host: str) -> asyncio.Lock:
        """Retrieves or creates an asyncio.Lock for rate limiting requests to a specific host."""
        if host not in self._host_locks:
            self._host_locks[host] = asyncio.Lock()
        return self._host_locks[host]

    def _log_retry(self, retry_state):
        """Logs retry attempts with retry state and exception information."""
        exc = retry_state.outcome.exception()
        attempt = retry_state.attempt_number
        logger.warning(f"Scraper retry attempt #{attempt} due to: {repr(exc)}")

    async def _fetch_with_retry(self, url: str) -> httpx.Response:
        """Executes the request with the tenacity retry policy.

        Retries on httpx.TransportError or 5xx server responses with exponential backoff.
        """
        retrier = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=5),
            retry=(
                retry_if_exception_type(httpx.TransportError) |
                retry_if_exception_type(HttpResponseError)
            ),
            before_sleep=self._log_retry,
            reraise=True,
        )

        async for attempt in retrier:
            with attempt:
                response = await self.client.get(url)
                if response.status_code >= 500:
                    raise HttpResponseError(response)
                return response

        # This line is theoretically unreachable due to reraise=True in AsyncRetrying
        raise RuntimeError("Retries failed to raise or return a response.")

    async def fetch(self, url: str) -> FetchResult:
        """Fetches a URL asynchronously with full compliance, rate limiting, and retries.

        Maintains safety and reliability by:
        1. Checking robots.txt before making a request.
        2. Restricting concurrent requests to the same host using a delay lock.
        3. Catching all exceptions to return a populated FetchResult.

        Args:
            url: The target URL to download.

        Returns:
            A FetchResult instance carrying the response html or details of the failure.
        """
        await self._ensure_robots_fetched()

        if not self.can_fetch(url):
            logger.warning(f"Scrape request disallowed by robots.txt for: {url}")
            return FetchResult(
                url=url,
                status_code=0,
                html="",
                fetched_at=datetime.now(timezone.utc),
                error="blocked_by_robots",
            )

        host = urlparse(url).netloc or self.base_domain
        lock = self._get_host_lock(host)

        async with lock:
            last_time = self._last_request_time.get(host, 0.0)
            now = time.time()
            elapsed = now - last_time
            if elapsed < self.rate_limit_delay:
                sleep_duration = self.rate_limit_delay - elapsed
                logger.info(f"Rate limiting {host}: sleeping for {sleep_duration:.2f}s")
                await asyncio.sleep(sleep_duration)

            logger.info(f"Fetching URL: {url}")
            try:
                response = await self._fetch_with_retry(url)
                return FetchResult(
                    url=url,
                    status_code=response.status_code,
                    html=response.text,
                    fetched_at=datetime.now(timezone.utc),
                    error=None,
                )
            except HttpResponseError as e:
                logger.error(f"Terminal HTTP failure for {url} (status {e.response.status_code})")
                return FetchResult(
                    url=url,
                    status_code=e.response.status_code,
                    html=e.response.text,
                    fetched_at=datetime.now(timezone.utc),
                    error=f"HTTP status error: {e.response.status_code}",
                )
            except httpx.TransportError as e:
                logger.error(f"Terminal transport failure for {url}: {e}")
                return FetchResult(
                    url=url,
                    status_code=0,
                    html="",
                    fetched_at=datetime.now(timezone.utc),
                    error=f"Transport error: {str(e)}",
                )
            except Exception as e:
                logger.error(f"Unexpected terminal failure for {url}: {e}")
                return FetchResult(
                    url=url,
                    status_code=0,
                    html="",
                    fetched_at=datetime.now(timezone.utc),
                    error=f"Unexpected error: {str(e)}",
                )
            finally:
                self._last_request_time[host] = time.time()

    async def close(self):
        """Closes the underlying httpx.AsyncClient."""
        await self.client.aclose()
