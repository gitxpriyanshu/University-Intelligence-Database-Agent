"""Planning loop agent component for discovering and ordering target crawl URLs.

Defines the UniversityConfig, CrawlTarget, CrawlPlan, and the Planner class.
The Planner utilizes keywords, pagination rules, and content-length indicators
to decide which pages to visit, their execution order, and whether JS-rendering
is required.
"""
import logging
from typing import Dict, List, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from uia.utils.http_client import ResilientHttpClient

logger = logging.getLogger(__name__)

# Heuristic keywords mapping each of the 10 university intelligence categories
# to likely substring path or anchor text indicators.
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "about": [
        "about", "history", "profile", "overview", "facts", "ranking", 
        "rankings", "introduce", "introduction", "glance", "governance"
    ],
    "tuition_fees": [
        "fee", "fees", "tuition", "cost-of-study", "finance", "financial", 
        "payment", "costs", "billing", "estimator", "expenses"
    ],
    "living_costs": [
        "living-cost", "living-costs", "expense", "expenses", "accommodation", 
        "rent", "budget", "cost-of-living", "housing", "residence", "hostel"
    ],
    "scholarships": [
        "scholarship", "scholarships", "funding", "award", "awards", 
        "bursary", "bursaries", "financial-aid", "grants", "fellowship"
    ],
    "acceptance_rate": [
        "acceptance-rate", "acceptance", "admission-stats", "admission-requirements", 
        "profile", "enrollment", "rate", "statistics", "selectivity"
    ],
    "graduate_employment": [
        "employment", "employability", "career", "careers", "graduate-outcome", 
        "outcomes", "destination", "destinations", "jobs", "placement"
    ],
    "average_salaries": [
        "salary", "salaries", "earnings", "income", "pay-scale", 
        "compensation", "wages", "remuneration"
    ],
    "visa_policies": [
        "visa", "visas", "permit", "international-student", "immigration", 
        "entry-requirements", "study-permit", "compliance"
    ],
    "intake_deadlines": [
        "deadline", "deadlines", "intake", "key-dates", "apply", 
        "application-dates", "calendar", "timeline", "semester"
    ],
    "course_listings": [
        "course", "courses", "subject", "subjects", "catalog", "catalogue", 
        "syllabus", "program", "programs", "handbook", "curriculum", "modules"
    ],
}


class UniversityConfig(BaseModel):
    """Configuration profile containing target metadata and seed URLs for a university."""
    name: str = Field(..., description="Common name of the university target.")
    country: str = Field(..., description="Country where the university is located.")
    base_url: str = Field(..., description="Main domain / homepage URL of the university.")
    seed_urls: Dict[str, List[str]] = Field(
        ...,
        description="Dictionary mapping each of the 10 data categories to starting seed URLs."
    )


class CrawlTarget(BaseModel):
    """A specific web page destination scheduled for data crawling."""
    url: str = Field(..., description="Absolute URL to be crawled.")
    needs_render: bool = Field(
        default=False,
        description="True if the page is a JS-rendered client-side app or empty shell."
    )


class CrawlPlan(BaseModel):
    """The compiled execution plan mapping categories to ordered crawl targets."""
    categories: Dict[str, List[CrawlTarget]] = Field(
        default_factory=dict,
        description="Crawl targets scheduled for each university database field."
    )


class Planner:
    """Computes a structured CrawlPlan using crawling seeds and path heuristics.

    Heuristics & Limits:
    - Same-Domain Restriction: Links must match the configured base domain.
    - Relevance Matching: Anchor texts or URL paths are matched against category-specific terms.
    - Pagination Queueing: Discovered pagination indicators (e.g. Next page, Page=2)
      will enqueue additional targets up to max_pages_per_category.
    - JS-Shell Detection: Pages with less than 200 characters of clean text are
      flagged as requiring headless browser rendering fallbacks.
    """

    def __init__(
        self,
        max_urls_per_category: int = 4,
        max_pages_per_category: int = 5,
    ):
        """Initializes the Planner.

        Args:
            max_urls_per_category: Maximum crawl targets compiled per field category.
            max_pages_per_category: Maximum page depth to follow for pagination.
        """
        self.max_urls_per_category = max_urls_per_category
        self.max_pages_per_category = max_pages_per_category

    def _is_pagination_link(self, anchor_text: str, href: str, a_tag: Any) -> bool:
        """Heuristically determines if an anchor tag represents page navigation."""
        text_lower = anchor_text.lower()
        href_lower = href.lower()

        # Check standard rel attribute
        rel_attr = a_tag.get("rel", [])
        rel_list = rel_attr if isinstance(rel_attr, list) else [rel_attr]
        if "next" in rel_list:
            return True

        # Check classes
        classes = a_tag.get("class", [])
        class_str = " ".join(classes).lower() if isinstance(classes, list) else str(classes).lower()
        if "next" in class_str or "pagination" in class_str:
            return True

        # Check for query parameters signaling pagination
        if "page=" in href_lower or "p=" in href_lower or "pg=" in href_lower:
            return True

        # Text matching
        for keyword in ["next", "older", ">", "»"]:
            if keyword in text_lower:
                return True

        return False

    def _is_relevant(self, category: str, anchor_text: str, href: str) -> bool:
        """Determines if a link matches keywords for a specific category."""
        text_lower = anchor_text.lower()
        path_lower = urlparse(href).path.lower()
        keywords = CATEGORY_KEYWORDS.get(category, [])

        for kw in keywords:
            if kw in text_lower or kw in path_lower:
                return True
        return False

    async def build_plan(self, config: UniversityConfig, http_client: ResilientHttpClient) -> CrawlPlan:
        """Examines seeds and returns a plan detailing crawl paths and rendering requirements.

        Args:
            config: Target university profile configuration.
            http_client: Active ResilientHttpClient for inspecting page structures.

        Returns:
            A populated CrawlPlan containing ordered CrawlTargets per category.
        """
        plan_categories: Dict[str, List[CrawlTarget]] = {}

        # Extract base domain to enforce same-domain constraints
        base_parsed = urlparse(config.base_url)
        base_domain = base_parsed.netloc or base_parsed.path
        if not base_domain:
            base_domain = config.base_url

        for category, seeds in config.seed_urls.items():
            logger.info(f"Analyzing seeds for category '{category}'")
            targets: List[CrawlTarget] = []
            visited: Set[str] = set()
            queue: List[str] = list(seeds)

            pages_fetched = 0

            while queue and len(targets) < self.max_urls_per_category:
                url = queue.pop(0)
                # Normalize URL by removing fragment identifiers
                url_normalized = url.split("#")[0]
                if url_normalized in visited:
                    continue
                visited.add(url_normalized)

                logger.debug(f"Planner processing page '{url_normalized}' in category '{category}'")
                result = await http_client.fetch(url_normalized)
                pages_fetched += 1

                if result.error or result.status_code >= 400:
                    err = result.error or f"HTTP status {result.status_code}"
                    logger.debug(f"Planning fetch error for '{url_normalized}': {err}")
                    # Retain seed entry even if failed so the main scraper has a chance to execute
                    if url_normalized not in [t.url for t in targets] and len(targets) < self.max_urls_per_category:
                        logger.debug(f"Adding failed page to plan as fallback: {url_normalized}")
                        targets.append(CrawlTarget(url=url_normalized, needs_render=False))
                    continue

                # Strip script and style markup to check clean visible text content
                soup = BeautifulSoup(result.html, "lxml")
                for element in soup(["script", "style", "noscript", "iframe"]):
                    element.decompose()
                visible_text = soup.get_text()
                clean_text = " ".join(visible_text.split())

                needs_render = len(clean_text) < 200
                if needs_render:
                    logger.debug(
                        f"Target URL '{url_normalized}' text size is {len(clean_text)} (under 200 threshold). "
                        "Marked needs_render=True."
                    )

                if url_normalized not in [t.url for t in targets] and len(targets) < self.max_urls_per_category:
                    targets.append(CrawlTarget(url=url_normalized, needs_render=needs_render))

                if len(targets) >= self.max_urls_per_category:
                    logger.debug(f"Hit max_urls_per_category ({self.max_urls_per_category}) for '{category}'")
                    break

                # Extract and filter child links
                page_soup = BeautifulSoup(result.html, "lxml")
                for a_tag in page_soup.find_all("a", href=True):
                    href = a_tag["href"]
                    abs_url = urljoin(url_normalized, href)
                    abs_url_normalized = abs_url.split("#")[0]

                    # Enforce same-domain crawling
                    link_parsed = urlparse(abs_url_normalized)
                    link_domain = link_parsed.netloc

                    if not (link_domain == base_domain or link_domain.endswith("." + base_domain)):
                        continue

                    if abs_url_normalized in visited:
                        continue

                    anchor_text = a_tag.get_text()

                    # Handle pagination enqueuing
                    if self._is_pagination_link(anchor_text, href, a_tag):
                        if pages_fetched < self.max_pages_per_category:
                            logger.debug(
                                f"Pagination link detected: '{abs_url_normalized}' ('{anchor_text.strip()}'). "
                                "Enqueueing."
                            )
                            queue.append(abs_url_normalized)
                        else:
                            logger.debug("Pagination depth limit reached. Skipping pagination path.")

                    # Handle relevant content discovery
                    elif self._is_relevant(category, anchor_text, href):
                        if abs_url_normalized not in [t.url for t in targets] and abs_url_normalized not in queue:
                            logger.debug(
                                f"Discovered relevant link for '{category}': '{abs_url_normalized}' "
                                f"('{anchor_text.strip()}')"
                            )
                            queue.append(abs_url_normalized)

            plan_categories[category] = targets

        return CrawlPlan(categories=plan_categories)
