"""LLM Extraction Engine.

Extracts structured, validated intelligence from crawled news articles and job descriptions
using the multi-provider LLM fallback chain. Ensures source URL preservation, zero fabrication,
and Pydantic schema validation.
"""

import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

import aiohttp
from pydantic import ValidationError

from src.config import PROCESSED_DATA_DIR
from src.extractors.schemas import ExtractedJobSchema, ExtractedNewsSchema
from src.services.export_service import export_service
from src.services.llm_service import LLMService
from src.utils.logger import get_logger

logger = get_logger("llm_extractor")


class ExtractionStats:
    """Tracks extraction attempts, successes, failures, and provider metrics."""

    def __init__(self) -> None:
        self.attempted: int = 0
        self.succeeded: int = 0
        self.failed: int = 0
        self.providers: Counter = Counter()
        self.fallbacks: int = 0

    def record_success(self, provider: str, fallbacks: int = 0) -> None:
        self.attempted += 1
        self.succeeded += 1
        self.providers[provider.upper()] += 1
        self.fallbacks += fallbacks

    def record_failure(self) -> None:
        self.attempted += 1
        self.failed += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "providers": dict(self.providers),
            "fallbacks": self.fallbacks,
        }


NEWS_EXTRACTION_SYSTEM = """You are a strict, factual intelligence extraction engine for artificial intelligence news.
Your task is to extract structured JSON from the provided article text.
CRITICAL RULES:
1. Output MUST be valid JSON only. Do not include introductory or concluding conversational prose.
2. Never invent, assume, or fabricate any facts, companies, or technologies.
3. If no companies are mentioned, return an empty array [].
4. If no technologies or models are mentioned, return an empty array [].
5. Missing details must be null or empty arrays.
"""

NEWS_EXTRACTION_PROMPT = """Extract intelligence from this news article into valid JSON:
Schema requirements:
{{
  "title": "<clean headline>",
  "summary": "<concise 1-2 sentence factual summary based ONLY on text>",
  "companies_mentioned": ["<company1>", "<company2>"],
  "technologies_mentioned": ["<technology/model1>", "<technology/model2>"],
  "category": "<one of: AI Research, Product Launch, Industry News, Regulation & Policy, Infrastructure & Hardware, Other>"
}}

Article Title: {title}
Article Source: {source}
Article Content:
{content}
"""


JOB_EXTRACTION_SYSTEM = """You are a strict, factual intelligence extraction engine for tech and AI job postings.
Your task is to extract structured JSON from the job posting.
CRITICAL RULES:
1. Output MUST be valid JSON only. Do not include markdown or conversational commentary.
2. Never fabricate required skills, qualifications, or company details.
3. If specific required skills are not stated, return an empty array [].
4. Missing fields must be null or empty arrays.
"""

JOB_EXTRACTION_PROMPT = """Extract intelligence from this job posting into valid JSON:
Schema requirements:
{{
  "job_title": "<standardized job title>",
  "company": "<company name>",
  "required_skills": ["<skill1>", "<skill2>"],
  "role_family": "<one of: Machine Learning, AI Research, Data Science, Software Engineering, Product & Management, Other>",
  "remote_status": "<one of: REMOTE, HYBRID, ONSITE>"
}}

Job Title: {title}
Company: {company}
Job Text / Description:
{content}
"""


async def extract_news_item(
    article: Dict[str, Any],
    llm_service: LLMService,
    session: Optional[aiohttp.ClientSession] = None,
    stats: Optional[ExtractionStats] = None,
) -> Optional[Dict[str, Any]]:
    """Extract structured intelligence from a single news record using LLM with fallback."""
    title = article.get("title", "")
    source = article.get("source_name", "News")
    content = article.get("description", "") or title
    url = article.get("url", "")

    prompt = NEWS_EXTRACTION_PROMPT.format(title=title, source=source, content=content)

    try:
        raw_json, provider, fallbacks = await llm_service.generate_json(
            prompt=prompt,
            system_instruction=NEWS_EXTRACTION_SYSTEM,
            session=session,
        )

        # Merge preserved source URL and ingestion timestamp
        raw_json["url"] = url
        raw_json["collectedAt"] = datetime.now(timezone.utc).isoformat()
        raw_json["schemaVersion"] = "1.0"
        raw_json["recordType"] = "EXTRACTED_NEWS"

        # Validate with Pydantic
        validated = ExtractedNewsSchema(**raw_json)
        logger.info(
            "Extracted news '%s' via %s (fallbacks: %d). Companies: %s, Tech: %s",
            validated.title[:40],
            provider.upper(),
            fallbacks,
            validated.companies_mentioned,
            validated.technologies_mentioned,
        )
        if stats:
            stats.record_success(provider, fallbacks)
        return validated.model_dump()

    except ValidationError as val_err:
        logger.warning("Pydantic validation failed for news article '%s': %s", title[:40], val_err)
        if stats:
            stats.record_failure()
        return None
    except Exception as exc:
        logger.warning("Failed to extract news article '%s': %s", title[:40], exc)
        if stats:
            stats.record_failure()
        return None


async def extract_job_item(
    job: Dict[str, Any],
    llm_service: LLMService,
    session: Optional[aiohttp.ClientSession] = None,
    stats: Optional[ExtractionStats] = None,
) -> Optional[Dict[str, Any]]:
    """Extract structured intelligence from a single job record using LLM with fallback."""
    title = job.get("job_title", "")
    company = job.get("company", "")
    content = f"Title: {title}. Company: {company}. Remote Status: {job.get('remote_status', '')}."
    url = job.get("url", "")

    prompt = JOB_EXTRACTION_PROMPT.format(title=title, company=company, content=content)

    try:
        raw_json, provider, fallbacks = await llm_service.generate_json(
            prompt=prompt,
            system_instruction=JOB_EXTRACTION_SYSTEM,
            session=session,
        )

        # Merge preserved source URL and ingestion timestamp
        raw_json["url"] = url
        raw_json["collectedAt"] = datetime.now(timezone.utc).isoformat()
        raw_json["schemaVersion"] = "1.0"
        raw_json["recordType"] = "EXTRACTED_JOB"

        # Validate with Pydantic
        validated = ExtractedJobSchema(**raw_json)
        logger.info(
            "Extracted job '%s @ %s' via %s (fallbacks: %d). Skills: %s, Role: %s",
            validated.job_title[:30],
            validated.company[:20],
            provider.upper(),
            fallbacks,
            validated.required_skills,
            validated.role_family,
        )
        if stats:
            stats.record_success(provider, fallbacks)
        return validated.model_dump()

    except ValidationError as val_err:
        logger.warning("Pydantic validation failed for job '%s': %s", title[:40], val_err)
        if stats:
            stats.record_failure()
        return None
    except Exception as exc:
        logger.warning("Failed to extract job '%s': %s", title[:40], exc)
        if stats:
            stats.record_failure()
        return None


async def extract_batch_news(
    articles: List[Dict[str, Any]],
    max_items: int = 5,
    llm_service: Optional[LLMService] = None,
    stats: Optional[ExtractionStats] = None,
) -> List[Dict[str, Any]]:
    """Extract intelligence from up to max_items news records."""
    service = llm_service or LLMService()
    target_articles = articles[:max_items]

    logger.info("Starting LLM extraction on %d news articles...", len(target_articles))
    extracted = []

    async with aiohttp.ClientSession() as session:
        for article in target_articles:
            res = await extract_news_item(article, service, session=session, stats=stats)
            if res:
                extracted.append(res)

    out_file = PROCESSED_DATA_DIR / "extracted_news.json"
    export_service.export_json(extracted, out_file)
    return extracted


async def extract_batch_jobs(
    jobs: List[Dict[str, Any]],
    max_items: int = 5,
    llm_service: Optional[LLMService] = None,
    stats: Optional[ExtractionStats] = None,
) -> List[Dict[str, Any]]:
    """Extract intelligence from up to max_items job records."""
    service = llm_service or LLMService()
    target_jobs = jobs[:max_items]

    logger.info("Starting LLM extraction on %d job records...", len(target_jobs))
    extracted = []

    async with aiohttp.ClientSession() as session:
        for job in target_jobs:
            res = await extract_job_item(job, service, session=session, stats=stats)
            if res:
                extracted.append(res)

    out_file = PROCESSED_DATA_DIR / "extracted_jobs.json"
    export_service.export_json(extracted, out_file)
    return extracted
