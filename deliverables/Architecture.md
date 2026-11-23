# AI Intelligence Ingestion Pipeline: System Architecture & Design Specification

**Document Version:** 1.0.0  
**Target Ingestion Capacity:** 1,000+ Entities per Core Category  
**Runtime Environment:** Python 3.10+ (AsyncIO, aiohttp, Pydantic v2, ReportLab, OpenPyXL)  
**Author:** AI Data Engineering Team  

---

## 1. Executive Summary & Pipeline Flow

The **AI Intelligence Ingestion Pipeline** is an enterprise-grade, asynchronous intelligence gathering engine designed to crawl, parse, normalize, enrich, and canonicalize multi-modal AI domain data. It unifies high-throughput structured ingestion across five critical ecosystem dimensions: **Research Papers**, **AI Startups**, **Commercial Products & Models**, **Fresh Ecosystem News**, and **Active AI Job Opportunities**.

```
[ Public APIs & Registries ]       [ Multi-Source Crawlers ]           [ Processing Engine ]           [ Storage & Delivery ]
  - arXiv API (Cornell Univ)   -->   asyncio / aiohttp Pool     -->   Strict 24h Freshness Filter  -->   Centralized ExportService
  - Y Combinator Directories   -->   (Non-blocking Coroutines)  -->   LLM Structured Extraction    -->   - JSON (data/raw/)
  - OpenRouter & Hugging Face  -->   Shared Async Retry &       -->   - Gemini 3.1 Flash Lite      -->   - CSV (data/processed/)
  - TechCrunch / VentureBeat   -->   Exponential Backoff        -->   - Fallback: Groq / DeepSeek  -->   Multi-Tab Excel Workbook
  - Remotive / Job Aggregators -->   Stargazer Lookup           -->   Entity Resolution Engine     -->   Architecture Specification
```

### End-to-End Orchestration (`main.py`)
1. **Concurrent Crawling Phase**: Concurrently initiates all 5 category crawlers using `asyncio.gather(..., return_exceptions=True)`, isolating failure domains so a slow or rate-limited external endpoint never aborts unaffected sources.
2. **Freshness Enforcement Phase**: Applies strict 24-hour publication window filtering to ephemeral feeds (News and Jobs), discarding stale articles and postings.
3. **Structured LLM Extraction Phase**: Invokes a 3-tier resilient fallback extraction chain (`Gemini 3.1 Flash-Lite` $\rightarrow$ `Groq LLaMA 3.3 70B` $\rightarrow$ `DeepSeek Chat`) on raw news and job descriptions, converting unstructured text into schema-compliant records.
4. **Entity Resolution & Canonicalization Phase**: Resolves company and product identities across datasets into global UUIDs, preventing duplicates while enforcing strict URL classification guardrails.
5. **Centralized Export Phase**: Dispatches clean records through `ExportService`, producing atomic JSON and normalized CSV files, followed by automated multi-tab Excel compilation.

---

## 2. Crawler Sources & Bulk Ingestion Strategy

| Domain | Primary Data Sources & Endpoints | Ingestion Mechanism | Target Volume | Provenance & Traceability |
| :--- | :--- | :--- | :---: | :--- |
| **Research Papers** | arXiv API (`export.arxiv.org/api/query`), Cornell AI Archive | Offset batch pagination (`max_results=100`), 3.5s spacing | **1,000** | Canonical arXiv URL (`arxiv.org/abs/...`), exact authors, publication timestamp |
| **AI Startups** | Y Combinator Directory (`artificial-intelligence`, `generative-ai`, `machine-learning`, `ai` feeds) | Multi-feed JSON aggregation, corporate suffix stripping | **1,000** | Traceable YC company directory URLs (`ycombinator.com/companies/{slug}`), verified website |
| **Products & Models** | OpenRouter Models API, Hugging Face Hub API, Developer Directories | API pagination, open-weights & proprietary model union | **1,000** | Model registry URLs (`openrouter.ai/models/...`, `huggingface.co/...`), clean product keys |
| **AI News** | TechCrunch AI, VentureBeat AI, Hacker News RSS feeds | XML/Atom stream parsing, 24h freshness filter | 50–100/day | Article canonical URL, publisher domain, verified UTC publication date |
| **AI Jobs** | Remotive AI/ML API, Jobicy, ArbeitNow developer feeds | REST polling, automated role & remote status classification | 300–500/day | Direct application URL, hiring company, employment arrangement (`REMOTE`/`HYBRID`/`ONSITE`) |

### Bulk Ingestion & Pagination Mechanics
- **arXiv Rate-Limit Mitigation**: arXiv limits requests per IP. The pipeline employs batch pagination (`start=0, 100, 200...`) throttled to one request every 3.5 seconds. On HTTP 429 / 503, an adaptive retry mechanism backs off progressively (15s $\rightarrow$ 25s $\rightarrow$ 35s). If the primary export cluster reaches IP capacity, it supplements authentic arXiv papers via the Cornell repository index.
- **Deduplication Engine**:
  - *Papers*: Deduplicated via `normalize_arxiv_id`, stripping protocol differences (`http://` vs `https://`) and version tags (`v1`, `v2`).
  - *Startups*: Deduplicated via normalized name and company slug, removing corporate suffixes (`Inc`, `Corp`, `LLC`, `PBC`).
  - *Products*: Deduplicated via compound key `{clean_company}:{clean_product_name}`.
- **GitHub Intelligence Enrichment**: Abstracts and descriptions are scanned with regular expressions (`github.com/{owner}/{repo}`) to extract public source code repositories. Stargazer counts are fetched with 2.5s timeouts. If GitHub returns HTTP 403 (unauthenticated rate limit), the crawler immediately freezes further calls, leaving missing star counts as explicit `null` (`None`) values rather than fabricating 0.

---

## 3. Freshness Policy & LLM Fallback Chain

### Strict 24-Hour Freshness Policy
For fast-moving domain categories (**News** and **Jobs**), stale data compromises intelligence utility. The pipeline applies a strict temporal cutoff:
$$\Delta t = t_{\text{collected}} - t_{\text{published}} \le 24.5\text{ hours}$$
- **Timezone Normalization**: All incoming date strings (RFC 2822, ISO 8601, UNIX epoch) are converted to explicit UTC `datetime` objects via `src/processors/date_parser.py`.
- **Clock Drift Tolerance**: A 30-minute grace window accounts for minor clock drift between origin servers. Outdated items and future dates beyond tolerance are permanently rejected.

```
       [ Raw Unstructured News / Job Payload ]
                          │
                          ▼
            [ Payload Bounding: Max 8,000 Chars ]
                          │
                          ▼
             [ Primary: Google Gemini 3.1 Flash Lite ]
             (REST: v1beta/models/gemini-3.1-flash-lite)
              ├── HTTP 200 & Valid JSON  ──────────────► [ Validated Schema ]
              └── HTTP 429 / 500 / 413 / Invalid JSON
                          │
                          ▼
             [ Fallback 1: Groq LLaMA 3.3 70B Versatile ]
             (OpenAI-compatible REST API)
              ├── HTTP 200 & Valid JSON  ──────────────► [ Validated Schema ]
              └── HTTP 429 / 500 / Timeout
                          │
                          ▼
             [ Fallback 2: DeepSeek Chat (V3) ]
              ├── HTTP 200 & Valid JSON  ──────────────► [ Validated Schema ]
              └── Failure ─────────────────────────────► [ Local Rule-Based Extraction ]
```

### Handling HTTP 413 (Payload Too Large) & HTTP 429 (Rate Limits)
- **HTTP 413 Protection**: Raw texts exceeding 8,000 characters are bounded and truncated with a clean warning notice prior to dispatch, preventing provider buffer overflow.
- **HTTP 429 Backoff**: When a provider emits HTTP 429 (Rate Limit), the shared retry utility inspects the `Retry-After` HTTP header. If absent, it computes exponential backoff with jitter: $t_{\text{wait}} = 2^{\text{attempt}} + \text{uniform}(0, 1)$. If retries exceed thresholds, it triggers instant provider fallback.

---

## 4. Entity Resolution & False-Positive Safeguards

Entity resolution unifies entity representations across datasets without destroying original source records. To resolve the critical risk of false-positive merges caused by shared hosting and aggregator portals, a strict multi-tier classification and validation architecture is enforced.

```
                      [ Incoming Entity Pair: A & B ]
                                     │
                                     ▼
                [ Step 1: URL Classification & Domain Guard ]
     Is URL a Generic Platform, Repo Directory, or Aggregator Portal?
                     ├── YES ──► Suppress EXACT_URL Matching
                     └── NO  ──► Check Root Domain Match
                                     │
                                     ▼
                  [ Step 2: Name Compatibility Guard ]
    Are entity names compatible? (e.g. "Cursor" vs "Mistral" = Incompatible)
                     ├── NO  ──► Keep Unresolved (Separate IDs)
                     └── YES ──► Evaluate Similarity
                                     │
                                     ▼
                  [ Step 3: Conservative Match Decision ]
     - Exact Domain Match + Compatible Name ──► Merge (Confidence: 0.90)
     - Exact Normalized Name Match          ──► Merge (Confidence: 0.95)
     - Fuzzy Levenshtein (Ratio >= 0.88)    ──► Merge (Confidence: 0.85)
     - Unmatched / Seed Record              ──► New Seed (Confidence: 0.00)
```

### URL Classification Engine
Every URL is categorized before matching:
1. `GENERIC_PLATFORM_URL`: Platforms hosting thousands of independent models/products (e.g., `huggingface.co`, `replicate.com`, `openrouter.ai`). Never used for entity identity.
2. `DIRECTORY_URL`: Aggregator directories (e.g., `github.com/ShaikhWarsi/free-ai-tools`, `ycombinator.com/companies`). Never merged across entities.
3. `DOCUMENTATION_PORTAL`: Shared API portals (e.g., `platform.openai.com/docs`).
4. `REPOSITORY_URL`: Specific source code repositories (`github.com/owner/repo`).
5. `ENTITY_SPECIFIC_URL`: Dedicated primary domain websites (`anthropic.com`, `cursor.com`).
6. `UNKNOWN_URL`: Unclassified URLs subject to conservative string comparison.

### Name Compatibility Logic
Even if two records reference related web properties, `are_names_compatible(name_a, name_b)` executes token containment and substring checks. Completely disjoint brand names (e.g., "Cursor" vs "Mistral La Plateforme") are strictly prevented from merging.

### Baseline Confidence Semantics
New canonical entities generated without matching an existing cluster are logged with `confidence_score = 0.0` under method `NEW_CANONICAL_SEED`, properly reflecting that no cross-entity merge occurred.

---

## 5. Storage Strategy & Scale Roadmap

### Dual Export Strategy (`ExportService`)
- **Raw Layer (`data/raw/*.json`)**: Full-fidelity JSON payloads capturing nested structures, raw metadata, author arrays, and original scraping timestamps.
- **Processed Layer (`data/processed/*.csv`)**: Flat tabular representations with semicolon-delimited array serialization, null normalization (`None` $\rightarrow$ empty string), and UTF-8 encoding.
- **Spreadsheet Deliverable (`deliverables/AI_Intelligence_Pipeline_Data.xlsx`)**: Comprehensive 6-tab openpyxl workbook featuring frozen header panes, auto-filters, zebra striping, and canonical entity ID linkage.

### Scale Limitations & Future Production Roadmap
1. **Out-of-Core Persistence**: In-memory Python sets for entity resolution scale efficiently to $\sim 50,000$ entities. Beyond $100,000$, transition to **DuckDB** or **PostgreSQL** with `pg_trgm` fuzzy indexing.
2. **Distributed Crawl Scheduling**: Currently orchestrated via asynchronous coroutines on a single node. For continuous $24/7$ multi-million item crawling, deploy distributed workers via **Temporal** or **Celery** with Redis-backed rate limiting.
3. **Hybrid Neural Entity Resolution**: Augment rule-based guards with sentence-transformer embeddings (`all-MiniLM-L6-v2`) to resolve high-variance semantic aliases.
