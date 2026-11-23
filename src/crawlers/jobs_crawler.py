"""AI and Tech Jobs Crawler.

Collects legitimate tech and AI job postings from 5 structured public endpoints and APIs
(Jobicy, Arbeitnow, Himalayas, Hacker News Jobs, Remotive), filters strictly to postings
published within the last 24 hours, normalizes timestamps to UTC, maps role families,
deduplicates by URL, and exports raw JSON and processed CSV outputs.
"""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

import aiohttp
import pandas as pd

from src.config import (
    DEFAULT_JOB_SOURCES,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
    REQUEST_TIMEOUT_SECONDS,
)
from src.processors.date_parser import is_within_last_24_hours, parse_to_utc
from src.processors.deduplication import deduplicate_by_url
from src.utils.logger import get_logger

logger = get_logger("jobs_crawler")


def classify_role_family(title: str, description: Optional[str] = None) -> str:
    """Classify job title and context into a standardized role family."""
    text = f"{title} {description or ''}".lower()

    if any(k in text for k in ["product manager", "project manager", "technical program manager", "director", "head of product"]):
        return "Product & Management"
    if any(k in text for k in ["research scientist", "ai researcher", "postdoc", "phd", "fundamental ai"]):
        return "AI Research"
    if any(k in text for k in ["machine learning", "ml engineer", "deep learning", "computer vision", "nlp", "llm", "genai", "prompt"]):
        return "Machine Learning"
    if any(k in text for k in ["data scientist", "data analyst", "data engineer", "analytics"]):
        return "Data Science"
    if any(k in text for k in ["software engineer", "developer", "backend", "frontend", "full stack", "devops", "cloud", "infra", "systems"]):
        return "Software Engineering"

    return "Other"


def infer_remote_status(remote_flag: Any, location_text: Optional[str] = None) -> str:
    """Normalize remote status into REMOTE, HYBRID, or ONSITE."""
    if remote_flag is True or str(remote_flag).lower() in ("true", "1", "yes"):
        return "REMOTE"

    text = f"{location_text or ''}".lower()
    if "hybrid" in text:
        return "HYBRID"
    if "remote" in text or "anywhere" in text or "worldwide" in text:
        return "REMOTE"
    if "onsite" in text or "on-site" in text:
        return "ONSITE"

    # Default to REMOTE for remote-first boards
    return "REMOTE"


async def fetch_jobicy_jobs(session: aiohttp.ClientSession, url: str) -> List[Dict[str, Any]]:
    """Fetch jobs from Jobicy public API."""
    headers = {"User-Agent": "ai-intelligence-ingestion-pipeline/1.0"}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("jobs", [])
    except Exception as exc:
        logger.warning("Jobicy fetch error: %s", exc)
    return []


async def fetch_arbeitnow_jobs(session: aiohttp.ClientSession, url: str) -> List[Dict[str, Any]]:
    """Fetch jobs from Arbeitnow public API."""
    headers = {"User-Agent": "ai-intelligence-ingestion-pipeline/1.0"}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", [])
    except Exception as exc:
        logger.warning("Arbeitnow fetch error: %s", exc)
    return []


async def fetch_himalayas_jobs(session: aiohttp.ClientSession, url: str) -> List[Dict[str, Any]]:
    """Fetch jobs from Himalayas public API."""
    headers = {"User-Agent": "ai-intelligence-ingestion-pipeline/1.0"}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("jobs", [])
    except Exception as exc:
        logger.warning("Himalayas fetch error: %s", exc)
    return []


async def fetch_remotive_jobs(session: aiohttp.ClientSession, url: str) -> List[Dict[str, Any]]:
    """Fetch jobs from Remotive public API."""
    headers = {"User-Agent": "ai-intelligence-ingestion-pipeline/1.0"}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("jobs", [])
    except Exception as exc:
        logger.warning("Remotive fetch error: %s", exc)
    return []


async def fetch_hn_jobs(session: aiohttp.ClientSession, url: str) -> List[Dict[str, Any]]:
    """Fetch latest job items from Hacker News Firebase API concurrently."""
    headers = {"User-Agent": "ai-intelligence-ingestion-pipeline/1.0"}
    items: List[Dict[str, Any]] = []

    async def fetch_single_hn_item(jid: int) -> Optional[Dict[str, Any]]:
        item_url = f"https://hacker-news.firebaseio.com/v0/item/{jid}.json"
        try:
            async with session.get(item_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and data.get("type") == "job":
                        return data
        except Exception:
            return None
        return None

    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:
            if resp.status == 200:
                job_ids = await resp.json()
                fetch_ids = job_ids[:30] if isinstance(job_ids, list) else []
                results = await asyncio.gather(*(fetch_single_hn_item(jid) for jid in fetch_ids), return_exceptions=True)
                for r in results:
                    if isinstance(r, dict):
                        items.append(r)
    except Exception as exc:
        logger.warning("Hacker News Jobs fetch error: %s", exc)
    return items


def parse_job_entry(item: Dict[str, Any], source_name: str, now_utc: datetime) -> Optional[Dict[str, Any]]:
    """Parse, validate, and normalize a job entry into the canonical schema within 24h."""
    # 1. Title and Company
    title = None
    company = None
    url = None
    raw_date = None
    remote_flag = True
    location = None

    if source_name == "Jobicy":
        title = item.get("jobTitle")
        company = item.get("companyName")
        url = item.get("url")
        raw_date = item.get("pubDate")
        location = item.get("jobGeo")
    elif source_name == "Arbeitnow":
        title = item.get("title")
        company = item.get("company_name")
        url = item.get("url")
        raw_date = item.get("created_at")
        remote_flag = item.get("remote")
        location = item.get("location")
    elif source_name == "Himalayas":
        title = item.get("title")
        company = item.get("companyName")
        url = item.get("url") or f"https://himalayas.app/jobs/{item.get('slug')}"
        raw_date = item.get("pubDate")
    elif source_name == "Hacker News Jobs":
        full_title = item.get("title", "")
        # HN job format is often "Company (YC X) is hiring Title"
        parts = full_title.split("Is Hiring", 1) if "Is Hiring" in full_title else full_title.split("is hiring", 1)
        if len(parts) == 2:
            company = parts[0].strip()
            title = parts[1].strip()
        else:
            title = full_title
            company = item.get("by") or "HN Poster"
        url = item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id')}"
        raw_date = item.get("time")
    elif source_name == "Remotive":
        title = item.get("title")
        company = item.get("company_name")
        url = item.get("url")
        raw_date = item.get("publication_date")
        location = item.get("candidate_required_location")

    if not title or not company or not url or not raw_date:
        return None

    # Parse and normalize publication date to UTC
    pub_dt = parse_to_utc(raw_date)
    if not pub_dt:
        return None

    # Strictly filter to the last 24 hours
    if not is_within_last_24_hours(pub_dt, reference_time=now_utc):
        return None

    role_family = classify_role_family(title)
    remote_status = infer_remote_status(remote_flag, location)

    return {
        "schemaVersion": "1.0",
        "recordType": "JOB",
        "job_title": title.strip(),
        "company": company.strip(),
        "url": url.strip(),
        "published_date": pub_dt.isoformat(),
        "remote_status": remote_status,
        "role_family": role_family,
        "source_name": source_name,
        "collectedAt": now_utc.isoformat(),
    }


async def crawl_jobs(
    sources: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Crawl configured job sources and return validated jobs published in the last 24 hours."""
    job_sources = sources or DEFAULT_JOB_SOURCES
    logger.info("Starting tech & AI jobs crawler with %d configured sources...", len(job_sources))

    all_jobs: List[Dict[str, Any]] = []
    now_utc = datetime.now(timezone.utc)

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        for src in job_sources:
            name = src["name"]
            url = src["url"]
            logger.info("Fetching jobs from source: '%s'...", name)

            items: List[Dict[str, Any]] = []
            if name == "Jobicy":
                items = await fetch_jobicy_jobs(session, url)
            elif name == "Arbeitnow":
                items = await fetch_arbeitnow_jobs(session, url)
            elif name == "Himalayas":
                items = await fetch_himalayas_jobs(session, url)
            elif name == "Hacker News Jobs":
                items = await fetch_hn_jobs(session, url)
            elif name == "Remotive":
                items = await fetch_remotive_jobs(session, url)

            valid_for_source = 0
            for item in items:
                parsed = parse_job_entry(item, name, now_utc)
                if parsed:
                    all_jobs.append(parsed)
                    valid_for_source += 1

            logger.info("Source '%s': retrieved %d total items, %d published within last 24h.", name, len(items), valid_for_source)

    # Deduplicate jobs by URL
    unique_jobs = deduplicate_by_url(all_jobs, url_key="url")
    logger.info(
        "Jobs crawl complete: %d raw eligible jobs -> %d unique jobs within last 24h.",
        len(all_jobs),
        len(unique_jobs),
    )

    # Save to disk
    save_job_outputs(unique_jobs)

    return unique_jobs


def save_job_outputs(jobs: List[Dict[str, Any]]) -> None:
    """Save collected jobs to data/raw/jobs.json and data/processed/jobs.csv."""
    raw_file = RAW_DATA_DIR / "jobs.json"
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d raw job records to %s", len(jobs), raw_file)

    df = pd.DataFrame(jobs)
    cols = [
        "schemaVersion",
        "recordType",
        "job_title",
        "company",
        "url",
        "published_date",
        "remote_status",
        "role_family",
        "source_name",
        "collectedAt",
    ]
    for col in cols:
        if col not in df.columns:
            df[col] = None
    df = df[cols]

    processed_file = PROCESSED_DATA_DIR / "jobs.csv"
    df.to_csv(processed_file, index=False, encoding="utf-8")
    logger.info("Saved %d processed job records to %s", len(df), processed_file)
