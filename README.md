# University Intelligence Database Agent (UIA)

The University Intelligence Database Agent (UIA) is an autonomous, AI-driven web scraping pipeline designed to extract structured information for academic institutions. The agent handles discovery planning, crawling, structured data extraction, and self-validation across 10 distinct intelligence fields: `about`, `tuition_fees`, `living_costs`, `scholarships`, `acceptance_rate`, `graduate_employment`, `average_salaries`, `visa_policies`, `intake_deadlines`, and `course_listings`. It saves the structured data to structured JSON and flattened CSV formats, which are queries-ready for downstream systems.

---

## Architecture Overview

The system runs as a sequential, multi-stage orchestration pipeline:

```
[Orchestrator]
      │
      ├──> 1. [Planner] ──────> Build dynamic CrawlPlan
      ├──> 2. [Crawler] ──────> Fetch & clean HTML (Playwright fallback)
      ├──> 3. [LLM Extractor] ──> Extract Pydantic schemas (Groq API)
      └──> 4. [Validator] ────> Compute confidence and validation flags
```

1. **Orchestrator** (`src/uia/agent/orchestrator.py`): Drives the execution flow for a target university config. It catches exceptions at the university level to guarantee that a failure in one target does not crash runs for other configured targets.
2. **Planner** (`src/uia/agent/planner.py`): Implements the **Planning Loop** requirement. It synthesizes configured seed URLs and maps out targets to crawl per database category.
3. **Crawler** (`src/uia/agent/crawler.py`): Fetches planned URLs, decomposes noise tags (scripts, styles, navigation, footers) using BeautifulSoup, and extracts visible page text.
4. **LLM Extractor** (`src/uia/utils/llm_client.py`): Performs schema-guided structured extraction using LLM completions. If the required Groq API key is missing, it falls back to a clearly marked `StubLLMClient` to emit empty schema-conforming placeholders.
5. **Validator** (`src/uia/agent/validator.py`): Implements the **Self-Validation** requirement. It checks fields for missing values, validates country-to-currency alignment, flags out-of-bound percentages, verifies date hierarchies, and computes field-level confidence scores.

### Agent Design Requirements

- **Planning Loop**: Managed in `src/uia/agent/planner.py`. It constructs a `CrawlPlan` categorizing target URLs for scraping.
- **Self-Validation**: Managed in `src/uia/agent/validator.py`. It inspects parsed fields against predefined constraints, reporting confidence metrics and generating a list of `ValidationFlag` entries with low, medium, or high severity.
- **Resilience**:
  - Compliance and Congestion Management: Managed in `src/uia/utils/http_client.py`. Respects `robots.txt` directives, implements concurrent locks for host-based rate limiting, and executes Tenacity-based exponential backoff retries (up to 3 attempts).
  - Headless Fallback: Managed in `src/uia/agent/crawler.py`. If page-rendering is needed, the crawler spawns Playwright Chromium to retrieve the dynamic DOM content before falling back to the standard HTTP client upon failures.

---

## Setup Instructions

### Prerequisites
- Python 3.10 or higher (or Docker)
- Internet connection for initial package installation and live scraping runs

### Local Installation
1. Clone the repository and navigate to the root directory.
2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
3. Install the package and dependencies:
   ```bash
   pip install -e .
   ```
4. Install the Playwright browser binaries:
   ```bash
   playwright install chromium
   ```

### Configuration
Copy the template configuration file:
```bash
cp .env.example .env
```
Edit `.env` to define the following parameters:
- `GROQ_API_KEY`: Your Groq API key. Leave blank to run using the `StubLLMClient`.
- `GROQ_MODEL`: The Groq model to target (defaults to `llama-3.3-70b-versatile`).

---

## Usage

The CLI tool is exposed via the entry point `uia`.

### Running the Pipeline
- **Full Live Scraping Run**:
  Scrapes all universities configured in the YAML profile.
  ```bash
  uia run
  ```
- **Single University Run**:
  Target a specific university by name.
  ```bash
  uia run --university "University of Toronto"
  ```
- **Page-Cached Incremental Run**:
  Checks the local hash database (`data/raw_cache/page_hashes.json`). Reuses previously extracted metrics for categories where the underlying web page content has not changed.
  ```bash
  uia run --incremental
  ```
- **Stub Mode**:
  Instantly emits dummy schema-conforming records without hitting network or API endpoints.
  ```bash
  uia run --stub
  ```

### Output Files
Scraped records land in:
- `data/output/universities.json`: Raw JSON array of Pydantic-modeled records.
- `data/output/universities.csv`: Flattened database layout mapping one row per `(university, field)` pair.

### Starting the Query API
Expose the database output through a FastAPI server:
```bash
uia serve
```
The server will run at `http://localhost:8000`. Query endpoints:
- `GET /universities`: List all university names.
- `GET /universities/{name}`: Get full record for a university.
- `GET /universities/{name}/{field}`: Get details (value, confidence, flags) for a specific field.

### Docker Setup
To run the agent and server with docker-compose:
- **Run pipeline default**:
  ```bash
  docker compose up --build
  ```
- **Start the query server**:
  ```bash
  docker compose run --rm -p 8000:8000 agent serve
  ```

---

## Adding a New University

To crawl and parse a new university, edit [config/universities.yaml](file:///Users/priyanshukv/Desktop/Projects/ViaCerta/config/universities.yaml) directly. No code modifications are required:

1. Append a new block under the `universities` list root:
   ```yaml
     - name: "Official University Name"
       country: "Target Country"
       base_url: "https://www.targetuni.edu"
       seed_urls:
         about:
           - "https://www.targetuni.edu/about"
         tuition_fees:
           - "https://www.targetuni.edu/admissions/fees"
         living_costs:
           - "https://www.targetuni.edu/campus-life/costs"
         scholarships:
           - "https://www.targetuni.edu/admissions/scholarships"
         acceptance_rate:
           - "https://www.targetuni.edu/about/quick-facts"
         graduate_employment:
           - "https://www.targetuni.edu/careers/outcomes"
         average_salaries:
           - "https://www.targetuni.edu/careers/salaries"
         visa_policies:
           - "https://www.targetuni.edu/international/visa"
         intake_deadlines:
           - "https://www.targetuni.edu/apply/deadlines"
         course_listings:
           - "https://www.targetuni.edu/academics/courses"
   ```
2. Save the file and run the target crawl:
   ```bash
   uia run --university "Official University Name"
   ```

---

## Evaluation

The evaluation suite calculates metrics relative to ground truth:

1. Execute the evaluation runner:
   ```bash
   python eval/eval_runner.py
   ```
2. Review results in `eval/eval_report.md`. This report details per-field accuracy tables, flagged-for-review items, and lists validation gaps for unverified fields.

---

## Known Limitations

- **Course Listings (`course_listings`)**: Many universities place course lookup metrics behind dynamic search structures (e.g. Toronto's course search or Melbourne's search catalog). Static URL parsing cannot input parameters or scroll programmatically through catalog databases.
- **Acceptance Rates (`acceptance_rate`) & Graduate Employment (`graduate_employment`)**: These details are frequently absent from top-level marketing pages. Universities often publish these values in annual PDF reports or through state-run agencies (e.g. QILT in Australia).
- **Tuition Fees (`tuition_fees`) & Living Costs (`living_costs`)**: Fee tables are highly variable and split by citizenship status, cohort term, and field of study. Interactive tuition fee lookup tools block static textual scraper extractions.

---

## Project Structure

```
.
├── Dockerfile
├── README.md
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── config/
│   └── universities.yaml
├── eval/
│   ├── eval_report.md
│   ├── eval_runner.py
│   └── ground_truth.json
├── src/
│   └── uia/
│       ├── __init__.py
│       ├── main.py
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── crawler.py
│       │   ├── orchestrator.py
│       │   ├── planner.py
│       │   └── validator.py
│       ├── api/
│       │   ├── __init__.py
│       │   └── server.py
│       ├── models/
│       │   ├── __init__.py
│       │   └── schema.py
│       └── utils/
│           ├── __init__.py
│           ├── cache.py
│           ├── http_client.py
│           └── llm_client.py
└── tests/
    ├── __init__.py
    ├── test_cache.py
    ├── test_http_client.py
    ├── test_llm_client.py
    ├── test_planner.py
    ├── test_schema.py
    ├── test_server.py
    └── test_validator.py
```
