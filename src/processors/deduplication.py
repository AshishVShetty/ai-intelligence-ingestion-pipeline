"""URL normalization and entity deduplication utilities."""

from typing import Any, Callable, Dict, List, Set
from urllib.parse import urlparse, urlunparse


def normalize_url(url: str) -> str:
    """Normalize URL by lowercasing scheme/host, removing trailing slashes, fragments, and tracking parameters."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower() or "https"
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")

        # Filter out common tracking query params (utm_*, ref, etc.)
        query_parts = []
        if parsed.query:
            for param in parsed.query.split("&"):
                if "=" in param:
                    key = param.split("=")[0].lower()
                    if key.startswith("utm_") or key in ("ref", "fbclid", "gclid"):
                        continue
                query_parts.append(param)
        clean_query = "&".join(query_parts)

        return urlunparse((scheme, netloc, path, parsed.params, clean_query, ""))
    except Exception:
        return url.strip().rstrip("/")


def deduplicate_by_url(
    records: List[Dict[str, Any]],
    url_key: str = "url",
) -> List[Dict[str, Any]]:
    """Deduplicate records based on normalized URL, preserving initial order."""
    seen: Set[str] = set()
    unique: List[Dict[str, Any]] = []

    for item in records:
        raw_url = item.get(url_key) or ""
        norm = normalize_url(raw_url)
        if norm and norm not in seen:
            seen.add(norm)
            unique.append(item)

    return unique
