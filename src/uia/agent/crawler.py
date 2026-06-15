"""Crawl execution engine for the University Intelligence Database Agent.

Provides the Crawler class that fetches URLs from a CrawlPlan, supporting
JavaScript rendering fallbacks with Playwright and HTML text cleaning.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from uia.agent.planner import CrawlPlan
from uia.utils.cache import PageCache
from uia.utils.http_client import FetchResult, ResilientHttpClient

logger = logging.getLogger(__name__)


class Crawler:
    """Fetches pages from a CrawlPlan and processes their content.

    Resilience & Execution Strategies:
    1. Headless Fallback: If a page needs JavaScript rendering (marked by planner),
       launches Playwright (Chromium) to retrieve fully-rendered DOM content.
    2. Graceful Degradation: If Playwright fails to initialize or render a page,
       falls back to standard ResilientHttpClient fetched content, logging a warning.
    3. Content Extraction: Strips noise tags (scripts, styles, navigation, footer)
       to produce a clean, dense visible text block for structured extraction.
    """

    def _clean_html(self, html: str) -> str:
        """Extracts visible text by decomposing layout/script markup.

        Strips script, style, noscript, iframe, nav, and footer sections.
        """
        if not html:
            return ""
        try:
            soup = BeautifulSoup(html, "lxml")
            for tag in ["script", "style", "noscript", "iframe", "nav", "footer"]:
                for el in soup.find_all(tag):
                    el.decompose()
            text = soup.get_text(separator=" ")
            return " ".join(text.split())
        except Exception as e:
            logger.warning(f"Failed to strip noise tags from HTML: {e}")
            return ""

    async def fetch_plan(
        self,
        plan: CrawlPlan,
        http_client: ResilientHttpClient,
        cache: Optional[PageCache] = None,
    ) -> Dict[str, List[FetchResult]]:
        """Downloads all pages detailed in a CrawlPlan.

        Args:
            plan: The planned targets mapping categories to URLs.
            http_client: The resilient client instance for standard requests.

        Returns:
            A dictionary mapping category names to list of fetched FetchResult instances.
        """
        results: Dict[str, List[FetchResult]] = {}

        # Scan if any target needs rendering to determine browser launch requirements
        any_render = any(
            target.needs_render
            for targets in plan.categories.values()
            for target in targets
        )

        browser = None
        playwright_context = None

        if any_render:
            logger.info("Plan contains JS-rendered targets. Launching Playwright Chromium...")
            try:
                playwright_context = await async_playwright().start()
                browser = await playwright_context.chromium.launch(headless=True)
                logger.info("Playwright browser launched successfully.")
            except Exception as e:
                logger.warning(
                    f"Playwright browser initialization failed: {e}. "
                    "All targets will fall back to standard HTTP retrieval."
                )
                any_render = False

        try:
            for category, targets in plan.categories.items():
                logger.info(f"Crawling targets for category '{category}' (Count: {len(targets)})")
                category_results: List[FetchResult] = []

                for target in targets:
                    result: Optional[FetchResult] = None

                    if target.needs_render and any_render and browser:
                        logger.info(f"Crawling JS page via Playwright: {target.url}")
                        try:
                            page = await browser.new_page()
                            # Use same User-Agent as http_client for consistency
                            await page.set_extra_http_headers({"User-Agent": http_client.user_agent})
                            response = await page.goto(target.url, timeout=30000, wait_until="networkidle")
                            html_content = await page.content()
                            status = response.status if response else 200
                            await page.close()

                            result = FetchResult(
                                url=target.url,
                                status_code=status,
                                html=html_content,
                                fetched_at=datetime.now(timezone.utc),
                                error=None,
                            )
                        except Exception as e:
                            logger.warning(
                                f"Playwright rendering failed for '{target.url}': {e}. "
                                "Retrying using standard HTTP client."
                            )

                    # Standard retrieval if Playwright was bypassed or failed
                    if not result:
                        result = await http_client.fetch(target.url)

                    # Extract clean visible text if the fetch was successful
                    if result and not result.error:
                        result.clean_text = self._clean_html(result.html)
                        if cache:
                            result.has_changed = cache.has_changed(result.url, result.clean_text)
                            if result.has_changed:
                                cache.update(result.url, result.clean_text)
                        else:
                            result.has_changed = True
                    elif result:
                        result.clean_text = ""
                        result.has_changed = True

                    category_results.append(result)

                results[category] = category_results

        finally:
            # Clean up browser processes
            if browser:
                await browser.close()
            if playwright_context:
                await playwright_context.stop()

        return results
