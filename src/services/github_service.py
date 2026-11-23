"""GitHub Service for repository star and metadata lookups."""

import asyncio
from pathlib import Path
import re
import sys
from typing import Any, Dict, Optional
import aiohttp

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from src.config import GITHUB_TOKEN
from src.utils.logger import get_logger

logger = get_logger("github_service")

GITHUB_REPO_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)",
    re.IGNORECASE,
)


class GitHubService:
    """Service to interact with GitHub REST API."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or GITHUB_TOKEN
        self.cache: Dict[str, Optional[int]] = {}

    def extract_repo_slug(self, url: str) -> Optional[str]:
        """Extract 'owner/repo' slug from a GitHub URL."""
        if not url:
            return None
        match = GITHUB_REPO_REGEX.search(url)
        if match:
            owner, repo = match.group(1), match.group(2)
            repo = repo.rstrip(".git")
            return f"{owner}/{repo}"
        return None

    async def get_star_count(
        self,
        url_or_slug: str,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> Optional[int]:
        """Fetch stargazers_count for a given repository URL or slug."""
        slug = self.extract_repo_slug(url_or_slug) if "github.com" in url_or_slug else url_or_slug
        if not slug:
            return None

        if slug in self.cache:
            return self.cache[slug]

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AI-Intelligence-Pipeline",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"

        api_url = f"https://api.github.com/repos/{slug}"

        local_session = session is None
        client = session or aiohttp.ClientSession()

        try:
            async with client.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    stars = data.get("stargazers_count")
                    self.cache[slug] = stars
                    return stars
                elif resp.status == 404:
                    self.cache[slug] = None
                    return None
                elif resp.status in (403, 429):
                    logger.warning("GitHub API rate limit hit for %s.", slug)
                    return None
                else:
                    return None
        except Exception as exc:
            logger.debug("GitHub star lookup failed for %s: %s", slug, exc)
            return None
        finally:
            if local_session:
                await client.close()


github_service = GitHubService()
