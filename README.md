# AI Intelligence Ingestion Pipeline

An enterprise-grade, asynchronous intelligence ingestion, extraction, and entity canonicalization engine for artificial intelligence market intelligence.

The pipeline continuously monitors, ingests, deduplicates, and resolves entities across research papers, AI startups, AI products/models, tech news feeds, and structured job postings.

---

## 1. Architecture & End-to-End Pipeline Flow

```
                                      main.py
                                         │
        ┌───────────────────┬────────────┴───────┬───────────────────┐
        ▼                   ▼                    ▼                   ▼
   [arXiv API]        [YC Startups]         [OpenRouter]       [RSS Feeds & Job APIs]
  Research Papers       Startups              Products               News & Jobs
   (100 Catalog)      (100 Catalog)        (100 Catalog)          (24h Freshness)
        │                   │                    │                   │
        ▼                   ▼                    ▼                   ▼
   Clean Schema        Clean Schema         Clean Schema      Strict 24h Filter
        │                   │                    │                   │
        └───────────────────┼────────────────────┘                   ▼
                            │                                LLM Extraction Engine
                            │                             (Gemini -> Groq -> DeepSeek)
                            │                                        │
                            ▼                                        ▼
                  Entity Resolution Engine                Validated Intelligence
                (Safe URL & Name Clustering)              (Extracted News & Jobs)
                            │                                        │
                            └────────────────────┬───────────────────┘
                                                 │
                                                 ▼
                                     Centralized Export Service
                                 data/raw/*.json & data/processed/*.csv
```

---

## 2. Project Directory Structure

```text
ai-intelligence-ingestion-pipeline/
├── src/
│   ├── __init__.py
│   ├── config.py                       # Configuration & environment settings
│   ├── crawlers/                       # Asynchronous intelligence crawlers
│   │   ├── __init__.py
│   │   ├── arxiv_crawler.py            # arXiv API + GitHub stars crawler
│   │   ├── startup_crawler.py          # Y Combinator AI startups crawler
│   │   ├── product_crawler.py          # OpenRouter + Free AI directory crawler
│   │   ├── news_crawler.py             # 5x Multi-source AI news RSS crawler
│   │   └── jobs_crawler.py             # 5x Structured AI/tech jobs crawler
│   ├── extractors/                     # LLM extraction & validation
│   │   ├── __init__.py
│   │   ├── llm_extractor.py            # Structured news & jobs extraction engine
│   │   └── schemas.py                  # Pydantic entity schemas
│   ├── processors/                     # Data normalization & entity resolution
│   │   ├── __init__.py
│   │   ├── date_parser.py              # ISO-8601 UTC date normalizer & 24h filter
│   │   ├── deduplication.py            # URL normalization & URL deduplication
│   │   └── entity_resolution.py        # Entity resolution & canonicalization engine
│   ├── services/                       # Infrastructure & shared services
│   │   ├── __init__.py
│   │   ├── export_service.py           # Centralized JSON/CSV export service
│   │   ├── github_service.py           # GitHub API stargazers service
│   │   └── llm_service.py              # 3-Tier LLM provider fallback engine
│   └── utils/                          # Cross-cutting utilities
│       ├── __init__.py
│       ├── logger.py                   # Formatted console/file logger
│       └── retry.py                    # Async exponential backoff & jitter utility
├── data/
│   ├── raw/                            # Ingested raw JSON datasets
│   │   ├── research_papers.json
│   │   ├── startups.json
│   │   ├── products.json
│   │   ├── news.json
│   │   └── jobs.json
│   └── processed/                      # Canonical CSVs & extracted intelligence
│       ├── research_papers.csv
│       ├── startups.csv
│       ├── products.csv
│       ├── news.csv
│       ├── jobs.csv
│       ├── extracted_news.json
│       ├── extracted_jobs.json
│       └── entity_mapping_log.csv
├── docs/
│   └── architecture.md                 # System architecture & schemas
├── tests/                              # Comprehensive test suite (43 unit tests)
│   ├── __init__.py
│   ├── test_crawlers.py                # Crawler & date parsing tests
│   ├── test_entity_resolution.py       # Resolution & regression tests
│   ├── test_llm_service.py             # Fallback, rate-limit & bounding tests
│   └── test_services_and_utils.py      # ExportService & Retry tests
├── .env.example                        # Template for environment configuration
├── .gitignore                          # Git ignore rules (secrets protected)
├── requirements.txt                    # Project dependencies
├── main.py                             # Pipeline orchestrator entrypoint
└── README.md                           # Documentation
```

---

## 3. Core Features & Capabilities

- **Multi-Source Asynchronous Ingestion**: Built on `aiohttp` and `asyncio` for non-blocking network I/O across APIs and feeds.
- **Strict 24-Hour Freshness Policy**: News articles and job postings are strictly validated against UTC ISO-8601 timestamps and filtered to the preceding 24 hours. Older or unverifiable items are safely excluded.
- **Resilient 3-Tier LLM Fallback Chain**:
  1. **Primary**: Google Gemini (`gemini-3.1-flash-lite` via REST)
  2. **Fallback 1**: Groq (`llama-3.3-70b-versatile` via REST)
  3. **Fallback 2**: DeepSeek (`deepseek-chat` via REST)
  - SDK-free REST requests, payload bounding to 8,000 characters to prevent HTTP 413, and exponential backoff on HTTP 429.
- **Audited Entity Resolution & Canonicalization**:
  - Deterministic ID format: `ent_<type>_<sha256_hash>`.
  - **URL Classification**: Restricts identity matching to `ENTITY_SPECIFIC_URL`. Generic platforms, documentation portals, and curated directories are strictly prevented from causing false-positive merges.
  - **Name Compatibility Guardrails**: Ensures distinct tools (e.g. `Cursor` vs `Mistral La Plateforme`, `OpenAI Moderation` vs `Whisper`) never collapse into a shared cluster.
- **Centralized Export Service**: Consistent serialization, null handling, and list-flattening across JSON and tabular CSV outputs.
- **Full Source Traceability**: Raw source URLs and timestamps are preserved on every single record. Zero data fabrication.

---

## 4. Ingestion Sources

| Catalog / Feed | Target | Primary Sources | Protocol | Freshness Policy |
| :--- | :--- | :--- | :--- | :--- |
| **Research Papers** | 1,000 papers | arXiv API (`cs.AI`, `cs.LG`, `cs.CL`, `cs.CV`, `stat.ML`) + GitHub Stars | REST / Atom XML | Catalog (1,000 unique) |
| **AI Startups** | 1,000 startups | Y Combinator AI Directories (`ai`, `genai`, `ml` feeds) | Multi-feed REST | Catalog (1,000 unique) |
| **AI Products & Models** | 1,000 products | OpenRouter API, Hugging Face Hub, Free AI Directories | REST API | Catalog (1,000 unique) |
| **AI & Tech News** | All available | Google News AI, The Verge AI, Wired AI, BBC Tech, Ars Technica | RSS Feeds | **Strictly $\le$ 24 Hours** |
| **Tech & AI Jobs** | All available | Jobicy, Arbeitnow, Hacker News Who Is Hiring, RemoteOK, Himalayas | Structured APIs | **Strictly $\le$ 24 Hours** |

---

## 5. Installation & Quickstart

### Prerequisites
- Python 3.10+
- Internet access for live API endpoints (or run sandboxed tests offline)

### Step 1: Clone Repository & Create Virtual Environment
```bash
git clone <repo-url>
cd ai-intelligence-ingestion-pipeline
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Populate `.env` with your API keys:
```env
# Optional GitHub token (increases rate limit from 60 to 5,000 req/hr)
GITHUB_TOKEN=your_github_token_here

# LLM Fallback Provider API Keys
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

---

## 6. Running the Pipeline

To execute the end-to-end pipeline (Ingestion $\rightarrow$ Freshness Filter $\rightarrow$ LLM Extraction $\rightarrow$ Entity Resolution $\rightarrow$ Export $\rightarrow$ Summary):
```bash
python main.py
```

### Running Individual Modules
- **ArXiv Crawler**: `python -m src.crawlers.arxiv_crawler`
- **Startup Crawler**: `python -m src.crawlers.startup_crawler`
- **Product Crawler**: `python -m src.crawlers.product_crawler`
- **News Crawler**: `python -m src.crawlers.news_crawler`
- **Jobs Crawler**: `python -m src.crawlers.jobs_crawler`
- **LLM Extraction Engine**: `python test_llm_extraction.py`
- **Entity Resolution Engine**: `python -m src.processors.entity_resolution`

---

## 7. Running the Test Suite

Run all 47 automated unit and regression tests:
```bash
python -m unittest discover tests -v
```

### Test Coverage Highlights
- `tests/test_crawlers.py`: 24-hour freshness filters, UTC date normalization, role classification, URL deduplication, arXiv ID protocol/version normalization, Hugging Face model parsing, OpenRouter pricing classification, and cross-feed startup deduplication.
- `tests/test_llm_service.py`: Multi-provider fallback (Gemini $\rightarrow$ Groq), rate limit 429 backoff, invalid JSON recovery, and 8,000 character payload bounding.
- `tests/test_entity_resolution.py`: URL classification, name compatibility, deterministic canonical IDs, and regression tests against false-positive merges (`Cursor`, `Windsurf`, `GitHub Copilot`, `OpenAI Moderation`, `Flux`).
- `tests/test_services_and_utils.py`: Centralized `ExportService` flattening and `async_retry` exponential backoff with jitter.

---

## 8. Output Artifacts & Deliverables

### Production Deliverables (`deliverables/`)
| Deliverable Path | Format | Description |
| :--- | :--- | :--- |
| `deliverables/AI_Intelligence_Pipeline_Data.xlsx` | Excel (.xlsx) | 6-tab production workbook containing Startups (1,000), Products (1,000), Research Papers (1,000), Jobs (330), News (68), and Entity Mapping Log (4,000) with frozen headers, auto-filters, and canonical entity UUID linkage. |
| `deliverables/Architecture.pdf` | PDF | 3-page publication-grade architecture specification and design document with running header/footer and page numbering. |
| `deliverables/Architecture.md` | Markdown | Editable source document for the architecture specification. |

### Data Stores (`data/`)
| Output Path | Format | Description |
| :--- | :--- | :--- |
| `data/raw/research_papers.json` | JSON | 1,000 raw arXiv paper records with authors, paper URLs, and GitHub stars |
| `data/processed/research_papers.csv` | CSV | Tabular research papers with author lists flattened with semicolons (1,000 records) |
| `data/raw/startups.json` | JSON | 1,000 raw AI startup records from Y Combinator directory feeds |
| `data/processed/startups.csv` | CSV | Tabular startup records including websites and employee counts (1,000 records) |
| `data/raw/products.json` | JSON | 1,000 raw AI products/models from OpenRouter, Hugging Face, and directories |
| `data/processed/products.csv` | CSV | Tabular product records with standardized pricing models (1,000 records) |
| `data/raw/news.json` | JSON | 24-hour fresh news articles normalized to UTC |
| `data/processed/news.csv` | CSV | Tabular fresh news records |
| `data/raw/jobs.json` | JSON | 24-hour fresh tech/AI jobs with normalized role families and remote status |
| `data/processed/jobs.csv` | CSV | Tabular fresh job postings |
| `data/processed/extracted_news.json` | JSON | LLM-extracted news intelligence (summary, companies, technologies, category) |
| `data/processed/extracted_jobs.json` | JSON | LLM-extracted job intelligence (required skills, role family, remote status) |
| `data/processed/entity_mapping_log.csv`| CSV | Lineage mapping audit log linking source records to canonical entities (4,000 records) |

---

## 9. Error Handling & Resilience Strategy

- **Isolated Crawler Tasks**: Each crawler task runs wrapped in error boundaries (`asyncio.gather(..., return_exceptions=True)`). A temporary outage in one source will never abort remaining crawlers.
- **Exponential Backoff with Jitter**: Network requests and rate-limited endpoints back off exponentially with full random jitter (`src/utils/retry.py`) to prevent thundering herds.
- **Rate Limit Delay Respect**: When APIs return `Retry-After` headers, the backoff scheduler honors the exact requested delay.
- **Fail-Safe LLM Extraction**: If an LLM provider fails, times out (30s), returns HTTP 429, or emits malformed JSON, execution cascades seamlessly to the next provider.
- **Non-Destructive Entity Resolution**: Source records are cloned and enriched. The original raw data remains untouched on disk.

---

## 10. Operational Limitations

1. **Pre-Website / Stealth Entities**: Startups or models without an official website rely on exact normalized name matching and can only merge when names match unambiguously.
2. **Dynamic Web Scraping**: The pipeline intentionally prioritizes official REST APIs, RSS feeds, and structured endpoints over brittle HTML web scrapers. Headless browser rendering is not required.
3. **Public API Rate Limits**: Unauthenticated GitHub star queries are capped at 60 requests/hour by GitHub. Providing a `GITHUB_TOKEN` in `.env` increases this ceiling to 5,000 requests/hour.
