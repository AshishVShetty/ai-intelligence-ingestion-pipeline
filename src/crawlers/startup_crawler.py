"""AI Startup Crawler.

Collects legitimate AI startup intelligence from accessible public sources and directories
(e.g., Y Combinator AI companies directory), extracting company details, website, description,
employee headcount, and traceable source URLs.
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
    DEFAULT_TARGET_STARTUPS,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
    REQUEST_TIMEOUT_SECONDS,
    YC_GENAI_URL,
    YC_ML_URL,
    YC_STARTUP_API_URL,
    YC_STARTUP_BACKUP_URL,
)
from src.services.export_service import export_service
from src.utils.logger import get_logger

logger = get_logger("startup_crawler")


def clean_text(text: Optional[str]) -> Optional[str]:
    """Normalize whitespace and strip unnecessary formatting."""
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned if cleaned else None


def normalize_company_name(name: str) -> str:
    """Normalize company name for deduplication, stripping punctuation and legal suffixes."""
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", name.lower())
    words = cleaned.split()
    suffixes = {"inc", "corp", "corporation", "llc", "ltd", "limited", "pbc"}
    if words and words[-1] in suffixes:
        words = words[:-1]
    return "".join(words)


async def fetch_json(session: aiohttp.ClientSession, url: str) -> Optional[List[Dict[str, Any]]]:
    """Fetch JSON data from a remote endpoint asynchronously with error handling."""
    headers = {"User-Agent": "ai-intelligence-ingestion-pipeline/1.0"}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:
            if resp.status == 200:
                return await resp.json()
            logger.warning("Endpoint %s returned status %d", url, resp.status)
    except asyncio.TimeoutError:
        logger.error("Timeout connecting to %s", url)
    except Exception as exc:
        logger.error("Error fetching data from %s: %s", url, exc)
    return None


async def crawl_startups(
    target_count: int = DEFAULT_TARGET_STARTUPS,
) -> List[Dict[str, Any]]:
    """Crawl AI startup information from public directory feeds.

    Saves raw results to data/raw/startups.json and processed records to data/processed/startups.csv.
    """
    logger.info("Starting AI startup crawler with target of %d companies...", target_count)

    startups: List[Dict[str, Any]] = []
    seen_identifiers = set()

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Aggregate multiple legitimate YC AI feeds to ensure rich coverage
        yc_feeds = [
            ("Artificial Intelligence", YC_STARTUP_API_URL),
            ("Generative AI", YC_GENAI_URL),
            ("Machine Learning", YC_ML_URL),
            ("AI Backup", YC_STARTUP_BACKUP_URL),
        ]
        items: List[Dict[str, Any]] = []
        for tag_label, feed_url in yc_feeds:
            logger.info("Fetching startups from YC feed '%s': %s", tag_label, feed_url)
            feed_items = await fetch_json(session, feed_url)
            if feed_items:
                items.extend(feed_items)
                logger.info("Retrieved %d entries from %s feed.", len(feed_items), tag_label)

        if not items:
            logger.error("Failed to retrieve startup data from public directories.")
            return []

        logger.info("Retrieved %d total raw startup entries across feeds. Normalizing records...", len(items))

        for item in items:
            name = clean_text(item.get("name"))
            if not name:
                continue

            norm_name = normalize_company_name(name)
            slug = item.get("slug") or norm_name
            if norm_name in seen_identifiers or slug in seen_identifiers:
                continue
            seen_identifiers.add(norm_name)
            seen_identifiers.add(slug)

            # Extract fields safely
            website = clean_text(item.get("website"))
            description = clean_text(item.get("long_description") or item.get("one_liner"))

            # Employee count / team size
            employee_count: Optional[int] = None
            raw_size = item.get("team_size")
            if raw_size is not None:
                try:
                    employee_count = int(raw_size)
                    if employee_count <= 0:
                        employee_count = None
                except (ValueError, TypeError):
                    employee_count = None

            # Traceable source URL on ycombinator.com
            source_url = item.get("url")
            if not source_url and slug:
                source_url = f"https://www.ycombinator.com/companies/{slug}"

            record: Dict[str, Any] = {
                "schemaVersion": "1.0",
                "recordType": "STARTUP",
                "company_name": name,
                "website": website,
                "description": description,
                "employee_count": employee_count,
                "source_name": "Y Combinator",
                "source_url": source_url or "https://www.ycombinator.com/companies",
                "collectedAt": datetime.now(timezone.utc).isoformat(),
            }

            startups.append(record)

            if len(startups) >= target_count:
                break

    logger.info("Successfully collected and deduplicated %d AI startups.", len(startups))

    # Save to disk via centralized ExportService
    save_startup_outputs(startups)

    return startups


def save_startup_outputs(startups: List[Dict[str, Any]]) -> None:
    """Save collected startups to data/raw/startups.json and data/processed/startups.csv via ExportService."""
    export_service.export_dataset(startups, "startups")
    logger.info("Saved %d startup records via ExportService.", len(startups))
