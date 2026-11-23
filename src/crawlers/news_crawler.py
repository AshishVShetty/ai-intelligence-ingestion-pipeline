"""AI News RSS Crawler.

Fetches and normalizes news articles from 5 legitimate AI and technology RSS feeds,
verifies publication dates within the last 24 hours, normalizes timestamps to UTC,
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
import feedparser
import pandas as pd

from src.config import (
    DEFAULT_NEWS_FEEDS,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
    REQUEST_TIMEOUT_SECONDS,
)
from src.processors.date_parser import is_within_last_24_hours, parse_to_utc
from src.processors.deduplication import deduplicate_by_url
from src.utils.logger import get_logger

logger = get_logger("news_crawler")


def strip_html(text: Optional[str]) -> Optional[str]:
    """Remove HTML tags and extra whitespace from feed descriptions."""
    if not text:
        return None
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean if clean else None


async def fetch_rss_feed(
    session: aiohttp.ClientSession,
    feed_config: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Fetch and parse a single RSS feed asynchronously with error handling."""
    name = feed_config["name"]
    url = feed_config["url"]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AI-Pipeline/1.0"}

    logger.info("Fetching RSS feed from '%s' (%s)...", name, url)
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:
            if resp.status != 200:
                logger.warning("Feed '%s' returned HTTP status %d. Skipping.", name, resp.status)
                return []
            content = await resp.text()
    except asyncio.TimeoutError:
        logger.warning("Feed '%s' timed out. Skipping.", name)
        return []
    except Exception as exc:
        logger.warning("Error fetching feed '%s': %s. Skipping.", name, exc)
        return []

    feed = feedparser.parse(content)
    if not feed.entries:
        logger.warning("Feed '%s' returned 0 parsed entries.", name)
        return []

    articles: List[Dict[str, Any]] = []
    skipped_no_date = 0
    skipped_older_than_24h = 0

    now_utc = datetime.now(timezone.utc)

    for entry in feed.entries:
        title = getattr(entry, "title", None)
        link = getattr(entry, "link", None)
        if not title or not link:
            continue

        # Extract publication date
        raw_date = getattr(entry, "published", None) or getattr(entry, "updated", None)
        if not raw_date and hasattr(entry, "published_parsed") and entry.published_parsed:
            import time
            raw_date = time.strftime("%Y-%m-%dT%H:%M:%SZ", entry.published_parsed)

        if not raw_date:
            skipped_no_date += 1
            continue

        pub_dt = parse_to_utc(raw_date)
        if not pub_dt:
            skipped_no_date += 1
            continue

        # Strictly filter to the last 24 hours
        if not is_within_last_24_hours(pub_dt, reference_time=now_utc):
            skipped_older_than_24h += 1
            continue

        # Description / summary
        summary = getattr(entry, "summary", None) or getattr(entry, "description", None)

        record = {
            "schemaVersion": "1.0",
            "recordType": "NEWS",
            "title": strip_html(title) or title.strip(),
            "source_name": name,
            "url": link.strip(),
            "published_date": pub_dt.isoformat(),
            "description": strip_html(summary),
            "collectedAt": now_utc.isoformat(),
        }
        articles.append(record)

    logger.info(
        "Feed '%s': found %d articles within last 24h (%d older than 24h, %d skipped without verified date).",
        name,
        len(articles),
        skipped_older_than_24h,
        skipped_no_date,
    )
    return articles


async def crawl_news(
    feeds: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Crawl configured RSS news feeds for articles published in the last 24 hours."""
    news_feeds = feeds or DEFAULT_NEWS_FEEDS
    logger.info("Starting AI news crawler with %d configured feeds...", len(news_feeds))

    all_articles: List[Dict[str, Any]] = []

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_rss_feed(session, feed) for feed in news_feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for feed_cfg, res in zip(news_feeds, results):
            if isinstance(res, Exception):
                logger.error("Feed '%s' encountered unexpected exception: %s", feed_cfg["name"], res)
            elif isinstance(res, list):
                all_articles.extend(res)

    # Deduplicate articles by normalized URL
    unique_articles = deduplicate_by_url(all_articles, url_key="url")
    logger.info(
        "News crawl complete: %d raw articles fetched -> %d unique articles within last 24h.",
        len(all_articles),
        len(unique_articles),
    )

    # Save outputs
    save_news_outputs(unique_articles)

    return unique_articles


def save_news_outputs(articles: List[Dict[str, Any]]) -> None:
    """Save collected news to data/raw/news.json and data/processed/news.csv."""
    raw_file = RAW_DATA_DIR / "news.json"
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d raw news records to %s", len(articles), raw_file)

    df = pd.DataFrame(articles)
    cols = [
        "schemaVersion",
        "recordType",
        "title",
        "source_name",
        "url",
        "published_date",
        "description",
        "collectedAt",
    ]
    for col in cols:
        if col not in df.columns:
            df[col] = None
    df = df[cols]

    processed_file = PROCESSED_DATA_DIR / "news.csv"
    df.to_csv(processed_file, index=False, encoding="utf-8")
    logger.info("Saved %d processed news records to %s", len(df), processed_file)
