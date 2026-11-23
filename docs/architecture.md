# AI Intelligence Ingestion Pipeline - Architecture

## 1. Overview
The **AI Intelligence Ingestion Pipeline** aggregates, validates, and normalizes AI and market intelligence across five primary modules:
1. **Research Papers**: arXiv Query API (categories: `cs.AI`, `cs.LG`, `cs.CL`, `cs.CV`, `stat.ML`) + GitHub API star lookup
2. **Startups**: Y Combinator AI Directory
3. **Products**: OpenRouter Model Catalog & Curated Developer AI Tools Directories
4. **News**: Multi-source AI & Technology RSS Feeds (strictly filtered to the last 24 hours)
5. **Jobs**: Public Structured Job APIs & Boards (strictly filtered to the last 24 hours)

---

## 2. Ingestion & Extraction Flow

```
┌────────────────────────────────────────────────────────────────────────┐
│                               main.py                                  │
└──────┬────────────┬────────────┬──────────────────┬─────────────────┬──┘
       │            │            │                  │                 │
       ▼            ▼            ▼                  ▼                 ▼
  [arXiv API]  [YC Startups]  [OpenRouter]    [5x RSS Feeds]     [5x Job APIs]
  (Research)    (Companies)    (Products)        (News)             (Jobs)
       │            │            │                  │                 │
       │            │            │            [24h Filter]       [24h Filter]
       ▼            ▼            ▼                  ▼                 ▼
   Normalize    Normalize    Normalize        Normalize UTC      Normalize UTC
       │            │            │                  │                 │
       └────────────┴────────────┼──────────────────┴─────────────────┘
                                 │
                                 ▼
                         Deduplication (URL)
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
       data/raw/*.json (JSON)          data/processed/*.csv (CSV)
                                 │
                                 ▼ (News & Jobs)
                 ┌───────────────────────────────┐
                 │     LLM Extraction Engine     │
                 │   (Gemini -> Groq -> DeepSeek)│
                 └───────────────┬───────────────┘
                                 │
                                 ▼
                     Pydantic Schema Validation
                                 │
                                 ▼
                  data/processed/extracted_*.json
```

---

## 3. Entity Schemas & Validation

### 3.1 Research Papers (`RESEARCH_PAPER`)
| Field | Type | Description |
| :--- | :--- | :--- |
| `schemaVersion` | string | Schema version (`"1.0"`) |
| `recordType` | string | Entity type (`"RESEARCH_PAPER"`) |
| `title` | string | Cleaned paper title |
| `authors` | list / string | Authors list (flattened with `;` in CSV) |
| `paper_url` | string | Canonical arXiv abstract URL |
| `github_url` | string / null | Extracted GitHub repository URL if present |
| `github_stars` | int / null | Star count from GitHub API |
| `published_date`| string | Submission date in ISO format |
| `source_name` | string | Origin identifier (`"arXiv"`) |
| `collectedAt` | string | Ingestion UTC timestamp (ISO-8601) |

### 3.2 Startups (`STARTUP`)
| Field | Type | Description |
| :--- | :--- | :--- |
| `schemaVersion` | string | Schema version (`"1.0"`) |
| `recordType` | string | Entity type (`"STARTUP"`) |
| `company_name` | string | Name of the startup / company |
| `website` | string / null | Company website URL |
| `description` | string / null | Business and product overview |
| `employee_count`| int / null | Team size / employee headcount |
| `source_name` | string | Data origin (`"Y Combinator"`) |
| `source_url` | string | Traceable profile URL |
| `collectedAt` | string | Ingestion UTC timestamp (ISO-8601) |

### 3.3 Products (`PRODUCT`)
| Field | Type | Description |
| :--- | :--- | :--- |
| `schemaVersion` | string | Schema version (`"1.0"`) |
| `recordType` | string | Entity type (`"PRODUCT"`) |
| `product_name` | string | Name of the AI product or model |
| `company_name` | string / null | Company / developer / organization |
| `website` | string / null | Product or company homepage |
| `description` | string / null | Functional description of the tool |
| `pricing_model` | string / null | One of `FREE`, `FREEMIUM`, `PAID`, `ENTERPRISE` |
| `source_name` | string | Data origin (`"OpenRouter"`, `"Free AI APIs Directory"`) |
| `source_url` | string | Traceable source URL |
| `collectedAt` | string | Ingestion UTC timestamp (ISO-8601) |

### 3.4 News (`NEWS`)
| Field | Type | Description |
| :--- | :--- | :--- |
| `schemaVersion` | string | Schema version (`"1.0"`) |
| `recordType` | string | Entity type (`"NEWS"`) |
| `title` | string | News headline |
| `source_name` | string | Feed name (e.g. `"Google News AI"`, `"The Verge AI"`) |
| `url` | string | Canonical article URL |
| `published_date`| string | Normalized ISO-8601 UTC timestamp |
| `description` | string / null | Clean text snippet or summary |
| `collectedAt` | string | Ingestion UTC timestamp (ISO-8601) |

### 3.5 Jobs (`JOB`)
| Field | Type | Description |
| :--- | :--- | :--- |
| `schemaVersion` | string | Schema version (`"1.0"`) |
| `recordType` | string | Entity type (`"JOB"`) |
| `job_title` | string | Position title |
| `company` | string | Hiring organization / company name |
| `url` | string | Direct posting URL |
| `published_date`| string | Normalized ISO-8601 UTC timestamp |
| `remote_status` | string | One of `REMOTE`, `HYBRID`, `ONSITE` |
| `role_family` | string | Standardized role family |
| `source_name` | string | Data origin (e.g. `"Jobicy"`, `"Arbeitnow"`, `"Himalayas"`) |
| `collectedAt` | string | Ingestion UTC timestamp (ISO-8601) |

---

## 4. LLM Extraction Engine & Provider Fallback Chain

### 4.1 Provider Chain Hierarchy
1. **Primary**: Google Gemini (`gemini-3.1-flash-lite` via Google AI Studio REST API)
2. **Fallback 1**: Groq (`llama-3.3-70b-versatile` via Groq REST API)
3. **Fallback 2**: DeepSeek (`deepseek-chat` via DeepSeek REST API)

### 4.2 Safeguards & Resilience
- **SDK-Free REST Architecture**: All calls use pure `aiohttp` asynchronous requests.
- **Failover Trigger Conditions**: Automatically fails over to the next provider on HTTP errors (5xx), network timeouts, missing API keys, or invalid JSON output.
- **Rate Limit Exponential Backoff**: On HTTP 429, performs exponential backoff (`wait = 2^attempt * 2.0s`) up to 2 retries before escalating to the fallback provider.
- **Payload Size Protection**: Input text is bounded to 8,000 characters to prevent HTTP 413 (Payload Too Large).
- **Anti-Hallucination Constraints**: Prompts enforce zero-invention rules; missing entities or skills default to empty lists (`[]`) or `null`.
- **Source URL Preservation**: Extracted schemas retain the original traceable `url`.

---

## 5. Entity Resolution and Canonicalization Engine

### 5.1 Overview & Core Principles
The **Entity Resolution Engine** (`src/processors/entity_resolution.py`) links, deduplicates, and canonicalizes disparate records across startups/companies, products, and research papers into stable canonical entity clusters while preventing false-positive merges caused by shared hosting, documentation portals, or curated lists.
- **Non-Destructive Preservation**: Raw source records are never mutated or deleted. Resolution produces enriched metadata (`canonical_entity_id`, `canonical_entity_name`) and appends immutable mapping events.
- **Deterministic Canonical IDs**: Structured prefix format `ent_<type>_<sha256_hash>` (e.g. `ent_comp_572c531059ad`) derived deterministically from canonical tokens, ensuring idempotent outputs across pipeline executions.
- **URL Classification & Evidence Restrictions**: URLs are systematically classified into functional categories (`ENTITY_SPECIFIC_URL`, `GENERIC_PLATFORM_URL`, `DIRECTORY_URL`, `DOCUMENTATION_PORTAL`, `REPOSITORY_URL`, `UNKNOWN_URL`). Shared directories, generic platforms, and documentation portals are strictly prohibited from serving as entity identity evidence.
- **Name Compatibility Guardrails**: Any potential match via URL or domain must pass a mandatory name compatibility check (`are_names_compatible`), guaranteeing that distinct products (e.g. `Cursor` vs `Mistral La Plateforme` or `OpenAI Moderation` vs `Whisper`) cannot merge even when sharing a source portal or company domain.
- **Product vs. Company Separation**: For products, parent company domains (e.g. `openai.com`, `google.com`, `replicate.com`) do not merge distinct products. Company resolution and product resolution remain strictly isolated entity types.

### 5.2 URL Classification Taxonomy

| Classification | Definition & Examples | Permitted for Identity Matching |
| :--- | :--- | :--- |
| `ENTITY_SPECIFIC_URL` | Dedicated corporate or product homepages (e.g. `https://anthropic.com`, `https://cursor.com`, `https://arxiv.org/abs/...`). | **Yes** (with compatible names) |
| `DOCUMENTATION_PORTAL` | Multi-product documentation and API portals (e.g. `platform.openai.com`, `docs.cloud.google.com`, `replicate.com/docs`). | **No** (never identity evidence) |
| `DIRECTORY_URL` | Curated lists, directories, or startup aggregators (e.g. `github.com/.../free-ai-tools`, `ycombinator.com/companies/...`). | **No** (never identity evidence) |
| `GENERIC_PLATFORM_URL` | Shared hosting / community platforms (e.g. `replicate.com`, `huggingface.co`, `pypi.org`, `kaggle.com`). | **No** (never identity evidence) |
| `REPOSITORY_URL` | Dedicated single-project source code repositories (e.g. `github.com/openai/whisper`). | **Only with compatible names** |
| `UNKNOWN_URL` | Empty, missing, or malformed URLs. | **No** |

### 5.3 Matching Hierarchy & Confidence Thresholds
Incoming records are evaluated against existing clusters using a strict top-down decision hierarchy:

| Hierarchy Level | Matching Method | Criteria & Rules | Confidence Score |
| :--- | :--- | :--- | :--- |
| **Level 0** | `ALREADY_RESOLVED` | Entity possesses an existing canonical ID in the session. Idempotent return. | `1.00` |
| **Level 1** | `EXACT_URL` | URL is `ENTITY_SPECIFIC_URL` (or `RESEARCH_PAPER` URL) AND names are compatible (`are_names_compatible`). | `1.00` |
| **Level 2** | `EXACT_DOMAIN` | Extracted root domain (`eTLD+1`) matches AND names are compatible. Never merges distinct products sharing a parent company domain. | `0.98` |
| **Level 3** | `EXACT_NORMALIZED_NAME` | Normalized lowercase alphanumeric name matches without conflicting root domains. Suffixes stripped (`Inc`, `LLC`, `Corp`, `Technologies`, etc.). | `0.95` |
| **Level 4** | `FUZZY_NAME` | Sequence similarity ratio $\ge 0.88$ (conservative threshold), no conflicting domains, and compatible core tokens. | `0.80 - 0.90` |
| **Unresolved** | `NEW_CANONICAL_SEED` | Ambiguous similarity ($0.65 \le \text{sim} < 0.88$), conflicting domains, or novel entity. Seeded as a new canonical entity. | `0.00` (baseline unmerged seed) |

### 5.4 Confidence Score Semantics
- **Pairwise Match Confidence (`0.80` to `1.00`)**: Assigned only when an incoming record successfully links to an existing cluster via verifiable identity evidence (`EXACT_URL`, `EXACT_DOMAIN`, `EXACT_NORMALIZED_NAME`, `FUZZY_NAME`, `ALREADY_RESOLVED`).
- **Unmatched Seed (`0.00`)**: A confidence score of `0.00` on `NEW_CANONICAL_SEED` indicates that the record formed a new cluster anchor without matching any existing entity, clearly separating ID generation determinism from match confidence.

### 5.5 Entity Mapping Log Schema (`data/processed/entity_mapping_log.csv`)
Every resolution event is logged with full lineage traceability:
- `original_entity_name`: Surface name ingested from source.
- `canonical_entity_name`: Cluster representative canonical name.
- `canonical_entity_id`: Deterministic unique identifier (`ent_<type>_<hash>`).
- `source_url`: Traceable origin URL of the record.
- `matching_method`: Decision branch (`EXACT_URL`, `EXACT_DOMAIN`, `EXACT_NORMALIZED_NAME`, `FUZZY_NAME`, `ALREADY_RESOLVED`, `NEW_CANONICAL_SEED`).
- `confidence_score`: Metric from `0.00` (unmatched seed) to `1.00` (exact match).
- `resolution_timestamp`: Ingestion timestamp in ISO-8601 UTC.
