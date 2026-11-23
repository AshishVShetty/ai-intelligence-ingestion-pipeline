"""arXiv Research Paper Crawler.

Fetches AI/ML research papers asynchronously from the official arXiv API,
extracts metadata, parses GitHub repository mentions, fetches star counts,
and stores outputs in both JSON (raw) and CSV (processed) formats.
"""

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional
import urllib.parse

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

import aiohttp
import feedparser
import pandas as pd

from src.config import (
    ARXIV_API_BASE_URL,
    ARXIV_DEFAULT_QUERY,
    ARXIV_REQUEST_DELAY,
    DEFAULT_PAGE_SIZE,
    DEFAULT_TARGET_PAPERS,
    GITHUB_TOKEN,
    MAX_RETRIES,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
    REQUEST_TIMEOUT_SECONDS,
)
from src.utils.logger import get_logger

logger = get_logger("arxiv_crawler")

# Regex to detect GitHub repository URLs
GITHUB_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)",
    re.IGNORECASE,
)

# Common non-repo paths on GitHub to ignore
IGNORED_OWNERS_AND_REPOS = {
    "site", "features", "topics", "collections", "trending", "events",
    "explore", "pricing", "about", "contact", "security", "issues",
    "pulls", "actions", "projects", "wiki", "pulse", "releases",
    "commit", "commits", "blob", "tree", "raw"
}

# In-memory cache for GitHub stars to avoid duplicate API calls
_github_stars_cache: Dict[str, Optional[int]] = {}
_github_rate_limited: bool = False


def extract_github_url(text: str) -> Optional[str]:
    """Extract and validate the first GitHub repository URL from text."""
    if not text:
        return None

    matches = GITHUB_REGEX.findall(text)
    for owner, repo in matches:
        owner = owner.strip(".,;:)'\"[]<>")
        repo = repo.strip(".,;:)'\"[]<>")
        if repo.endswith(".git"):
            repo = repo[:-4]

        # Filter out generic GitHub paths
        if (
            not owner
            or not repo
            or owner.lower() in IGNORED_OWNERS_AND_REPOS
            or repo.lower() in IGNORED_OWNERS_AND_REPOS
        ):
            continue

        return f"https://github.com/{owner}/{repo}"

    return None


async def fetch_github_stars(
    session: aiohttp.ClientSession,
    github_url: Optional[str],
    token: str = GITHUB_TOKEN,
) -> Optional[int]:
    """Retrieve stargazer count for a GitHub repository.

    Returns None if repository is not found, API limit exceeded, or on error.
    """
    global _github_rate_limited
    if not github_url or _github_rate_limited:
        return None

    if github_url in _github_stars_cache:
        return _github_stars_cache[github_url]

    match = GITHUB_REGEX.search(github_url)
    if not match:
        _github_stars_cache[github_url] = None
        return None

    owner, repo = match.group(1).strip(".,;:)'\"[]<>"), match.group(2).strip(".,;:)'\"[]<>")
    if repo.endswith(".git"):
        repo = repo[:-4]

    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ai-intelligence-ingestion-pipeline/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with session.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=2.5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                stars = data.get("stargazers_count")
                # Ensure stars is an integer or None (never fabricated)
                if stars is not None:
                    stars = int(stars)
                _github_stars_cache[github_url] = stars
                logger.info("Found %s stars for repository %s", stars, github_url)
                return stars
            elif resp.status == 404:
                logger.debug("GitHub repository not found: %s", github_url)
            elif resp.status in (403, 429):
                _github_rate_limited = True
                logger.info("GitHub API rate limit reached (%s). Disabling further GitHub requests.", resp.status)
            else:
                logger.debug("GitHub API returned status %s for %s", resp.status, github_url)
    except Exception as exc:
        logger.debug("Failed to fetch GitHub stars for %s: %s", github_url, exc)

    _github_stars_cache[github_url] = None
    return None


def clean_text(text: Optional[str]) -> str:
    """Normalize whitespace and strip newlines from string."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def reconstruct_abstract(abstract_inverted_index: Optional[Dict[str, List[int]]]) -> str:
    """Reconstruct plain abstract text from OpenAlex inverted index representation."""
    if not abstract_inverted_index or not isinstance(abstract_inverted_index, dict):
        return ""
    word_positions = []
    for word, positions in abstract_inverted_index.items():
        if isinstance(positions, list):
            for pos in positions:
                word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


def normalize_arxiv_id(raw_id: str) -> str:
    """Normalize arXiv identifier or link by normalizing protocol and removing version suffix."""
    cleaned = raw_id.strip()
    cleaned = re.sub(r"^https://", "http://", cleaned)
    return re.sub(r"v\d+$", "", cleaned)


async def fetch_arxiv_page(
    session: aiohttp.ClientSession,
    search_query: str,
    start: int,
    max_results: int,
) -> Optional[feedparser.FeedParserDict]:
    """Fetch and parse one page of results from the arXiv API with retries."""
    params = {
        "search_query": search_query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API_BASE_URL}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": "ai-intelligence-ingestion-pipeline/1.0"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("Fetching arXiv batch: start=%d, max_results=%d (attempt %d/%d)", start, max_results, attempt, MAX_RETRIES)
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    feed = feedparser.parse(content)
                    if feed.bozo and not feed.entries:
                        logger.warning("Feed parsing warning/error: %s", feed.bozo_exception)
                    return feed
                elif resp.status in (429, 503):
                    wait_time = attempt * 10 + 5
                    logger.warning("arXiv API rate limit / server busy (HTTP %d). Waiting %ds...", resp.status, wait_time)
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("arXiv API request failed with status HTTP %d", resp.status)
                    return None
        except asyncio.TimeoutError:
            wait_time = attempt * 5 + 5
            logger.warning("Timeout fetching arXiv page (attempt %d/%d). Waiting %ds...", attempt, MAX_RETRIES, wait_time)
            await asyncio.sleep(wait_time)
        except Exception as exc:
            logger.error("Network error fetching arXiv page: %s", exc)
            await asyncio.sleep(attempt * 5)

    return None


async def supplement_with_openalex_arxiv(
    session: aiohttp.ClientSession,
    target_count: int,
    seen_ids: set,
    papers: List[Dict[str, Any]],
) -> None:
    """Supplement authentic arXiv research papers via Cornell University's official arXiv collection on OpenAlex.

    Ensures that rate limits on export.arxiv.org do not prevent achieving the bulk dataset size
    while strictly preserving authentic paper provenance, author lists, published dates, and URLs.
    """
    logger.info(
        "Supplementing authentic arXiv papers via Cornell arXiv repository (target=%d, current=%d)...",
        target_count,
        len(papers),
    )
    page = 1
    headers = {"User-Agent": "ai-intelligence-ingestion-pipeline/1.0"}

    while len(papers) < target_count and page <= 10:
        url = (
            f"https://api.openalex.org/works?"
            f"filter=primary_location.source.id:S4306400194,concepts.id:C154945302"
            f"&per-page=200&page={page}&mailto=research@example.com"
        )
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:
                if resp.status != 200:
                    logger.warning("OpenAlex returned status %d on page %d", resp.status, page)
                    break
                data = await resp.json()
                results = data.get("results", [])
                if not results:
                    break

                batch_added = 0
                for work in results:
                    landing_url = work.get("primary_location", {}).get("landing_page_url") or ""
                    doi = work.get("doi") or ""
                    if "arxiv.org" in landing_url:
                        paper_url = landing_url
                    elif "arxiv" in doi.lower():
                        suffix = doi.split("/")[-1]
                        paper_url = f"http://arxiv.org/abs/{suffix}"
                    else:
                        paper_url = landing_url or doi

                    norm_id = normalize_arxiv_id(paper_url)
                    if not norm_id or norm_id in seen_ids:
                        continue
                    seen_ids.add(norm_id)

                    title = clean_text(work.get("title", ""))
                    if not title:
                        continue

                    authors = [
                        clean_text(a.get("author", {}).get("display_name", ""))
                        for a in work.get("authorships", [])
                        if a.get("author", {}).get("display_name")
                    ]

                    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
                    github_url = extract_github_url(f"{title} {abstract}")
                    github_stars = None
                    if github_url and not _github_rate_limited:
                        github_stars = await fetch_github_stars(session, github_url)

                    pub_date = work.get("publication_date", "")

                    record: Dict[str, Any] = {
                        "schemaVersion": "1.0",
                        "recordType": "RESEARCH_PAPER",
                        "title": title,
                        "authors": authors,
                        "paper_url": paper_url,
                        "github_url": github_url,
                        "github_stars": github_stars,
                        "published_date": pub_date,
                        "source_name": "arXiv",
                        "collectedAt": datetime.now(timezone.utc).isoformat(),
                    }

                    papers.append(record)
                    batch_added += 1
                    if len(papers) >= target_count:
                        break

                logger.info("OpenAlex arXiv page %d added %d papers. Total: %d/%d", page, batch_added, len(papers), target_count)
                page += 1
                await asyncio.sleep(0.5)
        except Exception as exc:
            logger.error("Error fetching supplemental arXiv papers from OpenAlex: %s", exc)
            break


async def crawl_arxiv_papers(
    target_count: int = DEFAULT_TARGET_PAPERS,
    page_size: int = DEFAULT_PAGE_SIZE,
    search_query: str = ARXIV_DEFAULT_QUERY,
) -> List[Dict[str, Any]]:
    """Crawl arXiv for research papers matching AI/ML categories until target_count is reached.

    Saves raw results to data/raw/research_papers.json and processed records to data/processed/research_papers.csv.
    """
    logger.info("Starting arXiv crawler: target=%d papers, query='%s'", target_count, search_query)

    papers: List[Dict[str, Any]] = []
    seen_ids = set()

    # Load existing validated papers from disk if available to minimize redundant network requests
    raw_path = RAW_DATA_DIR / "research_papers.json"
    if raw_path.exists():
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if isinstance(existing, list):
                    for p in existing:
                        p_id = normalize_arxiv_id(p.get("paper_url", ""))
                        if p_id and p_id not in seen_ids:
                            seen_ids.add(p_id)
                            papers.append(p)
            logger.info("Loaded %d existing validated papers from disk.", len(papers))
        except Exception as exc:
            logger.warning("Could not load existing papers: %s", exc)

    start = 0
    consecutive_failures = 0
    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        while len(papers) < target_count:
            fetch_size = min(page_size, (target_count - len(papers)) + 20)  # slight buffer for duplicates
            feed = await fetch_arxiv_page(session, search_query, start, fetch_size)

            if not feed or not getattr(feed, "entries", None):
                consecutive_failures += 1
                if consecutive_failures < 2:
                    logger.warning("No entries in current batch. Waiting 10s and retrying offset %d...", start)
                    await asyncio.sleep(10)
                    continue
                else:
                    logger.info("No more entries returned by arXiv API.")
                    break

            consecutive_failures = 0
            entries = feed.entries
            logger.info("Received %d entries from arXiv. Processing...", len(entries))

            batch_added = 0
            for entry in entries:
                raw_id = getattr(entry, "id", "")
                norm_id = normalize_arxiv_id(raw_id)
                if not norm_id or norm_id in seen_ids:
                    continue
                seen_ids.add(norm_id)

                title = clean_text(getattr(entry, "title", ""))
                summary = getattr(entry, "summary", "")
                comment = getattr(entry, "arxiv_comment", "")

                # Extract authors
                authors = [
                    clean_text(author.name)
                    for author in getattr(entry, "authors", [])
                    if hasattr(author, "name") and author.name
                ]

                # Determine paper URL
                paper_url = raw_id
                if hasattr(entry, "link") and entry.link:
                    paper_url = entry.link

                # Detect GitHub repository URL from summary, comment, and links
                text_to_search = f"{summary} {comment}"
                if hasattr(entry, "links"):
                    for link in entry.links:
                        text_to_search += f" {link.get('href', '')}"

                github_url = extract_github_url(text_to_search)
                github_stars = None
                if github_url and not _github_rate_limited:
                    github_stars = await fetch_github_stars(session, github_url)

                # Format published date
                published_date = getattr(entry, "published", "")

                record: Dict[str, Any] = {
                    "schemaVersion": "1.0",
                    "recordType": "RESEARCH_PAPER",
                    "title": title,
                    "authors": authors,
                    "paper_url": paper_url,
                    "github_url": github_url,
                    "github_stars": github_stars,
                    "published_date": published_date,
                    "source_name": "arXiv",
                    "collectedAt": datetime.now(timezone.utc).isoformat(),
                }

                papers.append(record)
                batch_added += 1

                if len(papers) >= target_count:
                    break

            logger.info(
                "Batch complete. Added %d new papers. Total collected: %d/%d",
                batch_added,
                len(papers),
                target_count,
            )

            start += len(entries)

            if len(papers) < target_count:
                logger.info("Waiting %.1f seconds before next arXiv request...", ARXIV_REQUEST_DELAY)
                await asyncio.sleep(ARXIV_REQUEST_DELAY)

        # If direct arXiv rate-limited or stopped short of target_count, supplement via Cornell arXiv repository
        if len(papers) < target_count:
            await supplement_with_openalex_arxiv(session, target_count, seen_ids, papers)

    # Save outputs
    save_outputs(papers)

    return papers


def save_outputs(papers: List[Dict[str, Any]]) -> None:
    """Save collected papers to data/raw/research_papers.json and data/processed/research_papers.csv via ExportService."""
    from src.services.export_service import export_service

    export_service.export_dataset(papers, "research_papers")
    logger.info("Saved %d research paper records via ExportService.", len(papers))
