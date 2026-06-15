# University Intelligence Database Agent

The University Intelligence Database Agent (UIA) is an AI-powered web scraping and planning agent designed to autonomously navigate university websites, locate relevant information, and extract comprehensive, structured data across multiple intelligence categories. Using a dynamic planning loop, robust self-validation, and resilient crawling strategies, the agent compiles detailed insights for academic institutions into standard, validated formats for downstream consumption.

## Known Limitations

When running the agent in environments without a live Groq API key (or when using `--stub` mode), all structured data fields in `universities.json` and `universities.csv` will be unpopulated (or set to default placeholders). In a live extraction pipeline, the following categories present unique extraction challenges:

- **Course Listings (`course_listings`)**: Many universities host course catalogs behind dynamic, JS-heavy search forms or complex databases (e.g. U of T's search-courses page or Melbourne's handbook search). A generic crawler cannot easily simulate the complex form inputs and pagination required to fetch deep course data within standard scraper bounds.
- **Acceptance Rates (`acceptance_rate`)** & **Graduate Employment (`graduate_employment`)**: These metrics are rarely published on standard university marketing pages. Instead, they are often locked inside PDF institutional reports, third-party survey engines (e.g. QILT in Australia), or external sites not reachable through primary crawls.
- **Tuition Fees (`tuition_fees`)** & **Living Costs (`living_costs`)**: Fee information is heavily segmented by citizenship, program of study, and term. Many universities utilize complex interactive "fee calculators" rather than readable text lists, which limit static/LLM text extraction success.
