# University Intelligence Database Agent

The University Intelligence Database Agent (UIA) is an AI-powered web scraping and planning agent designed to autonomously navigate university websites, locate relevant information, and extract comprehensive, structured data across multiple intelligence categories. Using a dynamic planning loop, robust self-validation, and resilient crawling strategies, the agent compiles detailed insights for academic institutions into standard, validated formats for downstream consumption.

## Known Limitations

When running the agent in environments without a live Groq API key (or when using `--stub` mode), all structured data fields in `universities.json` and `universities.csv` will be unpopulated (or set to default placeholders). In a live extraction pipeline, the following categories present unique extraction challenges:

- **Course Listings (`course_listings`)**: Many universities host course catalogs behind dynamic, JS-heavy search forms or complex databases (e.g. U of T's search-courses page or Melbourne's handbook search). A generic crawler cannot easily simulate the complex form inputs and pagination required to fetch deep course data within standard scraper bounds.
- **Acceptance Rates (`acceptance_rate`)** & **Graduate Employment (`graduate_employment`)**: These metrics are rarely published on standard university marketing pages. Instead, they are often locked inside PDF institutional reports, third-party survey engines (e.g. QILT in Australia), or external sites not reachable through primary crawls.
- **Tuition Fees (`tuition_fees`)** & **Living Costs (`living_costs`)**: Fee information is heavily segmented by citizenship, program of study, and term. Many universities utilize complex interactive "fee calculators" rather than readable text lists, which limit static/LLM text extraction success.

## Bonus Features

### 1. One-Command Docker Setup
The agent can be fully built and run inside a container containing all runtime dependencies, including Playwright browser binaries:
- **Build and Run (pipeline default)**:
  ```bash
  docker compose up --build
  ```
- **Run the API server**:
  ```bash
  docker compose run --rm -p 8000:8000 agent serve
  ```

### 2. FastAPI Query Server
A lightweight FastAPI query server exposes scraped metrics for downstream consumption. Start the server using:
```bash
uia serve
```
Then query the available endpoints:
- **List Scraped Universities**:
  ```bash
  curl http://localhost:8000/universities
  ```
- **Retrieve Full University Scraped Record**:
  ```bash
  curl http://localhost:8000/universities/university%20of%20melbourne
  ```
- **Retrieve Specific Metric Field Details (Value, Confidence, and Flags)**:
  ```bash
  curl http://localhost:8000/universities/university%20of%20toronto/about
  ```

### 3. Page-Level Incremental Scraping
To skip redundant network and LLM extraction steps, run the agent in incremental mode:
```bash
uia run --incremental
```
This enables a JSON-backed page cache (`data/raw_cache/page_hashes.json`). If page text is unchanged since the last run, the agent reuses the previously extracted database entry.

### 4. Zero-Code Configuration
Adding a new university requires no code modifications. Simply append a new entry to [universities.yaml](file:///Users/priyanshukv/Desktop/Projects/ViaCerta/config/universities.yaml):
```yaml
  - name: "New University"
    country: "United States"
    base_url: "https://newuni.edu"
    seed_urls:
      about:
        - "https://newuni.edu/about"
      # (add other target seed category URLs here...)
```
Run `uia run --university "New University"` to crawl only the new target.

