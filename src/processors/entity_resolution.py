"""Entity Resolution and Canonicalization Module.

Resolves, deduplicates, and canonicalizes entities (startups/companies, products, research papers)
across heterogeneous intelligence data sources using URL classification, domain validation,
exact normalized name matching, and conservative fuzzy matching rules while strictly preserving
source records and preventing false-positive merges across shared platforms/directories.
"""

from datetime import datetime, timezone
import difflib
from enum import Enum
import hashlib
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

import pandas as pd

from src.config import PROCESSED_DATA_DIR, RAW_DATA_DIR
from src.processors.deduplication import normalize_url
from src.utils.logger import get_logger

logger = get_logger("entity_resolution")


class URLClassification(str, Enum):
    """Categorization of URLs to govern their permissible use in entity identity matching."""

    ENTITY_SPECIFIC_URL = "ENTITY_SPECIFIC_URL"
    GENERIC_PLATFORM_URL = "GENERIC_PLATFORM_URL"
    DIRECTORY_URL = "DIRECTORY_URL"
    DOCUMENTATION_PORTAL = "DOCUMENTATION_PORTAL"
    REPOSITORY_URL = "REPOSITORY_URL"
    UNKNOWN_URL = "UNKNOWN_URL"


# Generic aggregation platforms and hosting domains to exclude from company/product domain matching
GENERIC_DOMAINS: Set[str] = {
    "github.com",
    "github.io",
    "gitlab.com",
    "ycombinator.com",
    "arxiv.org",
    "openrouter.ai",
    "huggingface.co",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "google.com",
    "facebook.com",
    "youtube.com",
    "medium.com",
    "substack.com",
    "producthunt.com",
    "notion.site",
    "discord.gg",
    "discord.com",
    "replicate.com",
    "pypi.org",
    "kaggle.com",
}

# Legal entity suffixes to remove during name canonicalization
LEGAL_SUFFIXES: Set[str] = {
    "inc",
    "incorporated",
    "llc",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "co",
    "company",
    "technologies",
    "technology",
    "labs",
    "lab",
    "software",
    "solutions",
    "group",
}

FUZZY_CONFIDENCE_THRESHOLD = 0.88
AMBIGUOUS_LOWER_THRESHOLD = 0.65


def normalize_entity_name(name: Optional[str]) -> str:
    """Normalize entity name: lowercase, strip punctuation, strip legal suffixes, and collapse whitespace."""
    if not name:
        return ""

    # 1. Lowercase and replace non-alphanumeric (except whitespace) with space
    text = name.strip().lower()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = text.split()

    # 2. Strip trailing legal/corporate suffixes if more than 1 token
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()

    return " ".join(tokens)


def classify_url(url: Optional[str]) -> URLClassification:
    """Classify a URL to determine whether it is entity-specific or a shared directory/portal."""
    if not url or not str(url).strip():
        return URLClassification.UNKNOWN_URL

    norm = normalize_url(str(url))
    if not norm:
        return URLClassification.UNKNOWN_URL

    try:
        parsed = urlparse(norm)
        host = (parsed.netloc or "").split(":")[0].lower().strip()
        path = (parsed.path or "").lower().rstrip("/")
        full = f"{host}{path}"

        if not host:
            return URLClassification.UNKNOWN_URL

        # 1. Directory / Curated list / Aggregator URLs
        directory_hosts = {
            "producthunt.com",
            "openrouter.ai",
            "theresanaiforthat.com",
            "futurepedia.io",
            "topai.tools",
        }
        if host in directory_hosts or any(host.endswith("." + dh) for dh in directory_hosts):
            return URLClassification.DIRECTORY_URL

        if "ycombinator.com" in host:
            return URLClassification.DIRECTORY_URL

        dir_path_keywords = (
            "free-ai-tools",
            "awesome-",
            "curated",
            "directory",
            "ai-tools",
            "list-of-",
            "resources",
        )
        if any(kw in path for kw in dir_path_keywords):
            return URLClassification.DIRECTORY_URL

        # 2. Documentation portals
        doc_subdomains = (
            "docs.",
            "developers.",
            "developer.",
            "api.docs.",
            "documentation.",
        )
        if (
            any(host.startswith(sub) for sub in doc_subdomains)
            or path.startswith(("/docs", "/documentation", "/api/docs", "/api-docs", "/guides"))
            or "platform.openai.com" in host
            or "docs.cloud.google.com" in host
            or "cloud.google.com/docs" in full
        ):
            return URLClassification.DOCUMENTATION_PORTAL

        # 3. Generic hosting / community platforms
        platform_hosts = {
            "replicate.com",
            "huggingface.co",
            "pypi.org",
            "colab.research.google.com",
            "kaggle.com",
            "medium.com",
            "substack.com",
            "twitter.com",
            "x.com",
            "linkedin.com",
            "discord.gg",
            "discord.com",
        }
        if host in platform_hosts or any(host.endswith("." + ph) for ph in platform_hosts):
            return URLClassification.GENERIC_PLATFORM_URL

        # 4. GitHub repository URLs (single repo: github.com/<owner>/<repo>)
        if "github.com" in host or "gitlab.com" in host:
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 2:
                return URLClassification.REPOSITORY_URL
            return URLClassification.GENERIC_PLATFORM_URL

        # 5. ArXiv research paper URLs
        if "arxiv.org" in host:
            return URLClassification.ENTITY_SPECIFIC_URL

        # 6. Entity-specific domain
        if "." in host:
            return URLClassification.ENTITY_SPECIFIC_URL

        return URLClassification.UNKNOWN_URL
    except Exception:
        return URLClassification.UNKNOWN_URL


def are_names_compatible(name_a: str, name_b: str) -> bool:
    """Verify that two names are compatible before allowing URL or domain identity merge.

    Prevents unrelated entities sharing a directory or platform URL from merging.
    """
    norm_a = normalize_entity_name(name_a)
    norm_b = normalize_entity_name(name_b)

    if not norm_a or not norm_b:
        return False

    # Exact normalized name
    if norm_a == norm_b:
        return True

    # Substring containment for brands/suffixes (e.g. "AssemblyAI" and "AssemblyAI Docs")
    shorter, longer = (norm_a, norm_b) if len(norm_a) <= len(norm_b) else (norm_b, norm_a)
    if len(shorter) >= 4 and shorter in longer:
        # Shorter must be at least 40% length of longer to prevent small-word collisions
        if len(shorter) / len(longer) >= 0.40:
            return True

    # Sequence similarity ratio
    sim = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()
    if sim >= 0.85:
        return True

    # Core meaningful tokens overlap
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    generic_tokens = {"ai", "ml", "api", "cloud", "platform", "tool", "tools", "docs"}
    meaningful_a = tokens_a - generic_tokens
    meaningful_b = tokens_b - generic_tokens
    if meaningful_a and meaningful_b:
        if (
            meaningful_a == meaningful_b
            or meaningful_a.issubset(meaningful_b)
            or meaningful_b.issubset(meaningful_a)
        ):
            if sim >= 0.60:
                return True

    return False


def extract_root_domain(url: Optional[str]) -> Optional[str]:
    """Extract registered root domain (eTLD+1), stripping subdomains and generic platforms."""
    if not url:
        return None
    try:
        norm_url = normalize_url(url)
        if not norm_url:
            return None
        parsed = urlparse(norm_url)
        host = (parsed.netloc or "").split(":")[0].lower().strip()
        if not host or "." not in host:
            return None

        # Ignore shared hosting/aggregation platforms
        if host in GENERIC_DOMAINS or any(host.endswith("." + g) for g in GENERIC_DOMAINS):
            return None

        # Extract root domain (e.g. careers.anthropic.com -> anthropic.com)
        parts = host.split(".")
        # Common two-part ccTLDs: co.uk, com.au, co.jp, org.uk, etc.
        if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "edu") and len(parts[-1]) == 2:
            root = ".".join(parts[-3:])
        elif len(parts) >= 2:
            root = ".".join(parts[-2:])
        else:
            root = host

        if root in GENERIC_DOMAINS:
            return None

        return root
    except Exception:
        return None


def generate_canonical_id(entity_type: str, canonical_name: str) -> str:
    """Generate deterministic canonical entity ID based on entity type and canonical name tokens."""
    norm = normalize_entity_name(canonical_name) or "unknown"
    digest = hashlib.sha256(f"{entity_type.lower()}:{norm}".encode("utf-8")).hexdigest()[:12]
    type_code = entity_type.lower()[:4]
    return f"ent_{type_code}_{digest}"


class CanonicalEntityCluster:
    """Represents a resolved canonical entity cluster."""

    def __init__(
        self,
        canonical_id: str,
        canonical_name: str,
        entity_type: str,
        primary_url: Optional[str] = None,
        primary_domain: Optional[str] = None,
    ):
        self.canonical_id = canonical_id
        self.canonical_name = canonical_name
        self.entity_type = entity_type
        self.normalized_name = normalize_entity_name(canonical_name)
        self.domains: Set[str] = {primary_domain} if primary_domain else set()
        self.urls: Set[str] = {normalize_url(primary_url)} if primary_url else set()
        self.aliases: Set[str] = {canonical_name}

    def add_evidence(
        self,
        name: str,
        url: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> None:
        if name:
            self.aliases.add(name)
        if url:
            norm_u = normalize_url(url)
            if norm_u:
                self.urls.add(norm_u)
        if domain:
            self.domains.add(domain)


class EntityResolver:
    """Performs deterministic entity resolution and canonicalization across entities."""

    def __init__(self, fuzzy_threshold: float = FUZZY_CONFIDENCE_THRESHOLD):
        self.fuzzy_threshold = fuzzy_threshold
        # Mapping from canonical_id -> CanonicalEntityCluster
        self.clusters: Dict[str, CanonicalEntityCluster] = {}
        # Entity mapping log rows
        self.mapping_logs: List[Dict[str, Any]] = []

    def resolve_entity(
        self,
        entity_name: str,
        entity_type: str,
        source_url: str,
        website: Optional[str] = None,
        already_canonical_id: Optional[str] = None,
    ) -> Tuple[str, str, str, float]:
        """Resolve an incoming entity against existing clusters using strict URL classification and name compatibility.

        Returns:
            Tuple of (canonical_entity_id, canonical_entity_name, matching_method, confidence_score)
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        original_name = (entity_name or "").strip()
        norm_name = normalize_entity_name(original_name)
        target_domain = extract_root_domain(website) if website else None
        target_website = normalize_url(website) if website else ""
        target_source_url = normalize_url(source_url) if source_url else ""

        # Classify URLs to restrict identity matching evidence
        website_class = classify_url(target_website) if target_website else URLClassification.UNKNOWN_URL
        source_class = classify_url(target_source_url) if target_source_url else URLClassification.UNKNOWN_URL

        # 0. Idempotence: Already resolved entity
        if already_canonical_id and already_canonical_id in self.clusters:
            cluster = self.clusters[already_canonical_id]
            cluster.add_evidence(original_name, target_website or target_source_url, target_domain)
            log_entry = {
                "original_entity_name": original_name,
                "canonical_entity_name": cluster.canonical_name,
                "canonical_entity_id": cluster.canonical_id,
                "source_url": source_url,
                "matching_method": "ALREADY_RESOLVED",
                "confidence_score": 1.0,
                "resolution_timestamp": now_iso,
            }
            self.mapping_logs.append(log_entry)
            return cluster.canonical_id, cluster.canonical_name, "ALREADY_RESOLVED", 1.0

        candidate_match: Optional[Tuple[CanonicalEntityCluster, str, float]] = None

        # 1. EXACT_URL Match (confidence: 1.0)
        # Permissible ONLY when:
        # - Target URL is ENTITY_SPECIFIC_URL (or RESEARCH_PAPER matching paper URL)
        # - Target URL is NOT a DIRECTORY_URL, GENERIC_PLATFORM_URL, or DOCUMENTATION_PORTAL
        # - Entity names are compatible
        # - Entity types strictly match
        if target_website and website_class == URLClassification.ENTITY_SPECIFIC_URL:
            for cluster in self.clusters.values():
                if cluster.entity_type == entity_type and target_website in cluster.urls:
                    if are_names_compatible(original_name, cluster.canonical_name):
                        candidate_match = (cluster, "EXACT_URL", 1.0)
                        break
        elif target_source_url and entity_type == "RESEARCH_PAPER":
            for cluster in self.clusters.values():
                if cluster.entity_type == entity_type and target_source_url in cluster.urls:
                    candidate_match = (cluster, "EXACT_URL", 1.0)
                    break

        # 2. EXACT_DOMAIN Match (confidence: 0.98)
        # Permissible ONLY when:
        # - Root domain is entity-specific (not in GENERIC_DOMAINS)
        # - Names are compatible (for both COMPANY and PRODUCT, preventing multi-product domain collisions)
        if not candidate_match and target_domain:
            for cluster in self.clusters.values():
                if cluster.entity_type == entity_type and target_domain in cluster.domains:
                    if are_names_compatible(original_name, cluster.canonical_name):
                        candidate_match = (cluster, "EXACT_DOMAIN", 0.98)
                        break

        # 3. EXACT_NORMALIZED_NAME Match (confidence: 0.95)
        # Permissible when normalized names match exactly and no conflicting entity-specific domains exist
        if not candidate_match and norm_name:
            for cluster in self.clusters.values():
                if cluster.entity_type == entity_type and norm_name == cluster.normalized_name:
                    # Do not merge if both possess conflicting registered domains
                    if target_domain and cluster.domains and target_domain not in cluster.domains:
                        logger.warning(
                            f"Name match collision rejected due to conflicting domains: "
                            f"'{original_name}' (domain: {target_domain}) vs '{cluster.canonical_name}' (domains: {cluster.domains})"
                        )
                        continue
                    candidate_match = (cluster, "EXACT_NORMALIZED_NAME", 0.95)
                    break

        # 4. FUZZY_NAME Match (confidence: 0.80 - 0.90)
        # Conservative fuzzy matching with strict domain compatibility and name compatibility
        if not candidate_match and norm_name and len(norm_name) >= 3:
            best_sim = 0.0
            best_cluster: Optional[CanonicalEntityCluster] = None
            conflicting_domain = False

            for cluster in self.clusters.values():
                if cluster.entity_type != entity_type:
                    continue
                if target_domain and cluster.domains and target_domain not in cluster.domains:
                    conflicting_domain = True
                    continue

                sim = difflib.SequenceMatcher(None, norm_name, cluster.normalized_name).ratio()
                if sim > best_sim:
                    best_sim = sim
                    best_cluster = cluster

            if best_cluster and best_sim >= self.fuzzy_threshold:
                if are_names_compatible(original_name, best_cluster.canonical_name):
                    score = round(0.82 + (best_sim - self.fuzzy_threshold) * 0.65, 2)
                    score = min(0.90, max(0.80, score))
                    candidate_match = (best_cluster, "FUZZY_NAME", score)
            elif best_sim >= AMBIGUOUS_LOWER_THRESHOLD or conflicting_domain:
                logger.info(
                    f"Ambiguous or conflicting match kept unresolved for '{original_name}' "
                    f"(best_sim={best_sim:.2f}, conflicting_domain={conflicting_domain})"
                )

        # 5. Process match or seed new cluster
        if candidate_match:
            cluster, method, confidence = candidate_match
            # Only record URL in cluster if it is entity-specific
            record_url = target_website if website_class == URLClassification.ENTITY_SPECIFIC_URL else (
                target_source_url if entity_type == "RESEARCH_PAPER" else None
            )
            cluster.add_evidence(original_name, record_url, target_domain)
            canonical_id = cluster.canonical_id
            canonical_name = cluster.canonical_name
        else:
            # Seed new canonical entity cluster
            canonical_id = generate_canonical_id(entity_type, original_name)
            canonical_name = original_name
            record_url = target_website if website_class == URLClassification.ENTITY_SPECIFIC_URL else (
                target_source_url if entity_type == "RESEARCH_PAPER" else None
            )
            cluster = CanonicalEntityCluster(
                canonical_id=canonical_id,
                canonical_name=canonical_name,
                entity_type=entity_type,
                primary_url=record_url,
                primary_domain=target_domain,
            )
            self.clusters[canonical_id] = cluster
            method = "NEW_CANONICAL_SEED"
            # 0.0 indicates an unmatched initial seed (no pairwise match)
            confidence = 0.0

        # Record in mapping log
        log_entry = {
            "original_entity_name": original_name,
            "canonical_entity_name": canonical_name,
            "canonical_entity_id": canonical_id,
            "source_url": source_url,
            "matching_method": method,
            "confidence_score": confidence,
            "resolution_timestamp": now_iso,
        }
        self.mapping_logs.append(log_entry)

        return canonical_id, canonical_name, method, confidence

    def get_mapping_logs_df(self) -> pd.DataFrame:
        """Return all mapping logs as a Pandas DataFrame."""
        columns = [
            "original_entity_name",
            "canonical_entity_name",
            "canonical_entity_id",
            "source_url",
            "matching_method",
            "confidence_score",
            "resolution_timestamp",
        ]
        return pd.DataFrame(self.mapping_logs, columns=columns)

    def export_mapping_log(self, output_path: Optional[Path] = None) -> Path:
        """Export the mapping logs to CSV format using the centralized ExportService."""
        target_path = output_path or (PROCESSED_DATA_DIR / "entity_mapping_log.csv")
        from src.services.export_service import export_service

        export_service.export_csv(self.mapping_logs, target_path)
        logger.info(f"Exported {len(self.mapping_logs)} entity resolution mapping records to {target_path}")
        return target_path


def resolve_all_intelligence_entities(
    startups: Optional[List[Dict[str, Any]]] = None,
    products: Optional[List[Dict[str, Any]]] = None,
    papers: Optional[List[Dict[str, Any]]] = None,
    export_csv: bool = True,
) -> Tuple[EntityResolver, Dict[str, List[Dict[str, Any]]]]:
    """Resolve and link entities across Startups, Products, and Research Papers without mutating original inputs."""
    import json

    resolver = EntityResolver()

    # Load from raw directory if not provided
    if startups is None:
        startup_file = RAW_DATA_DIR / "startups.json"
        if startup_file.exists():
            with open(startup_file, "r", encoding="utf-8") as f:
                startups = json.load(f)
        else:
            startups = []

    if products is None:
        product_file = RAW_DATA_DIR / "products.json"
        if product_file.exists():
            with open(product_file, "r", encoding="utf-8") as f:
                products = json.load(f)
        else:
            products = []

    if papers is None:
        paper_file = RAW_DATA_DIR / "research_papers.json"
        if paper_file.exists():
            with open(paper_file, "r", encoding="utf-8") as f:
                papers = json.load(f)
        else:
            papers = []

    resolved_startups: List[Dict[str, Any]] = []
    resolved_products: List[Dict[str, Any]] = []
    resolved_papers: List[Dict[str, Any]] = []

    # 1. Resolve Startups / Companies
    for item in startups:
        record = dict(item)
        c_id, c_name, method, conf = resolver.resolve_entity(
            entity_name=record.get("company_name", ""),
            entity_type="COMPANY",
            source_url=record.get("source_url", ""),
            website=record.get("website"),
            already_canonical_id=record.get("canonical_entity_id"),
        )
        record["canonical_entity_id"] = c_id
        record["canonical_entity_name"] = c_name
        resolved_startups.append(record)

    # 2. Resolve Products
    for item in products:
        record = dict(item)
        c_id, c_name, method, conf = resolver.resolve_entity(
            entity_name=record.get("product_name", ""),
            entity_type="PRODUCT",
            source_url=record.get("source_url", ""),
            website=record.get("website"),
            already_canonical_id=record.get("canonical_entity_id"),
        )
        record["canonical_entity_id"] = c_id
        record["canonical_entity_name"] = c_name

        # Also link product's parent company if present
        parent_company = record.get("company_name")
        if parent_company:
            comp_id, comp_name, _, _ = resolver.resolve_entity(
                entity_name=parent_company,
                entity_type="COMPANY",
                source_url=record.get("source_url", ""),
                website=record.get("website"),
            )
            record["canonical_company_id"] = comp_id
            record["canonical_company_name"] = comp_name

        resolved_products.append(record)

    # 3. Resolve Research Papers
    for item in papers:
        record = dict(item)
        c_id, c_name, method, conf = resolver.resolve_entity(
            entity_name=record.get("title", ""),
            entity_type="RESEARCH_PAPER",
            source_url=record.get("paper_url", ""),
            website=record.get("github_url"),
            already_canonical_id=record.get("canonical_entity_id"),
        )
        record["canonical_entity_id"] = c_id
        record["canonical_entity_name"] = c_name
        resolved_papers.append(record)

    if export_csv:
        resolver.export_mapping_log()

    return resolver, {
        "startups": resolved_startups,
        "products": resolved_products,
        "papers": resolved_papers,
    }


if __name__ == "__main__":
    logger.info("Executing Entity Resolution and Canonicalization Pipeline...")
    resolver, datasets = resolve_all_intelligence_entities(export_csv=True)
    df = resolver.get_mapping_logs_df()
    print(f"Total entity mappings generated: {len(df)}")
    print(f"Unique canonical entities: {df['canonical_entity_id'].nunique()}")
    print("\nMatching method breakdown:")
    print(df["matching_method"].value_counts())
