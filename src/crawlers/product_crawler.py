"""AI Product Crawler.

Collects legitimate AI product and model intelligence from accessible public directories and APIs
(e.g., Developer AI APIs directory, Developer AI tools index, OpenRouter models directory),
extracting product name, company/startup, website, description, pricing model (FREE, FREEMIUM,
PAID, ENTERPRISE, or None), and traceable source URLs.
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
    DEFAULT_TARGET_PRODUCTS,
    FREE_AI_APIS_DIRECTORY_URL,
    FREE_AI_TOOLS_DIRECTORY_URL,
    HUGGINGFACE_MODELS_API_URL,
    OPENROUTER_MODELS_API_URL,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
    REQUEST_TIMEOUT_SECONDS,
)
from src.services.export_service import export_service
from src.utils.logger import get_logger

logger = get_logger("product_crawler")

# Recognized pricing models according to specification
VALID_PRICING_MODELS = {"FREE", "FREEMIUM", "PAID", "ENTERPRISE"}


def clean_text(text: Optional[str]) -> Optional[str]:
    """Normalize whitespace and strip HTML/markdown tags."""
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned if cleaned else None


def extract_clean_url(text: Optional[str]) -> Optional[str]:
    """Extract a clean HTTP/HTTPS URL from a string or markdown link."""
    if not text:
        return None
    m = re.search(r"https?://[^\s)\]]+", text)
    if m:
        return m.group(0).strip(".,;:)'\"")
    return text.strip() if text.strip() else None


def normalize_product_key(name: str, company: Optional[str] = None) -> str:
    """Normalize product identifier for deduplication."""
    clean_name = re.sub(r"[^a-zA-Z0-9]", "", name.lower())
    clean_company = re.sub(r"[^a-zA-Z0-9]", "", (company or "").lower())
    return f"{clean_company}:{clean_name}"


def determine_pricing_model(evidence_text: Optional[str]) -> Optional[str]:
    """Infer one of FREE, FREEMIUM, PAID, ENTERPRISE from pricing evidence, or return None."""
    if not evidence_text:
        return None

    text = evidence_text.lower()

    # Enterprise cues
    if "enterprise" in text or "contact sales" in text or "custom pricing" in text:
        return "ENTERPRISE"

    # Freemium cues (free tier combined with quotas, limits, or pro upgrades)
    freemium_keywords = [
        "freemium", "free tier", "free plan", "free credits", "trial", "hobby",
        "requests/day", "tokens/day", "req/min", "req/day", "quota", "per month free"
    ]
    if any(k in text for k in freemium_keywords):
        return "FREEMIUM"

    # Strictly free / open-source cues
    if "100% free" in text or "completely free" in text or "open source" in text or text == "free":
        return "FREE"

    # Paid cues
    paid_keywords = ["$", "per 1m", "paid", "usage-based", "subscription", "/mo", "cents"]
    if any(k in text for k in paid_keywords):
        return "PAID"

    return None


async def fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """Fetch raw text/markdown from a URL asynchronously."""
    headers = {"User-Agent": "ai-intelligence-ingestion-pipeline/1.0"}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:
            if resp.status == 200:
                return await resp.text()
            logger.warning("Endpoint %s returned HTTP status %d", url, resp.status)
    except Exception as exc:
        logger.error("Error fetching text from %s: %s", url, exc)
    return None


async def fetch_json(session: aiohttp.ClientSession, url: str) -> Optional[Dict[str, Any]]:
    """Fetch JSON data from an API endpoint asynchronously."""
    headers = {"User-Agent": "ai-intelligence-ingestion-pipeline/1.0"}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:
            if resp.status == 200:
                return await resp.json()
            logger.warning("Endpoint %s returned HTTP status %d", url, resp.status)
    except Exception as exc:
        logger.error("Error fetching JSON from %s: %s", url, exc)
    return None


def parse_free_ai_apis_directory(content: str) -> List[Dict[str, Any]]:
    """Parse developer AI platform products from the Free AI APIs directory markdown."""
    products = []
    # Markdown table format: | [API Name](url) | Description | Free Tier | Auth | Docs |
    pattern = re.compile(
        r"\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*(?:\[[^\]]*\]\(([^)]+)\)|([^|]*))\|"
    )

    for line in content.splitlines():
        match = pattern.search(line)
        if not match:
            continue

        raw_name = match.group(1).strip()
        website = extract_clean_url(match.group(2))
        desc = match.group(3).strip()
        free_tier = match.group(4).strip()
        raw_doc_url = match.group(6) or match.group(7) or website
        doc_url = extract_clean_url(raw_doc_url) or website

        # Filter out header lines
        if raw_name.lower() in ("api", "column", "name"):
            continue

        pricing_model = determine_pricing_model(free_tier) or "FREEMIUM"

        record = {
            "schemaVersion": "1.0",
            "recordType": "PRODUCT",
            "product_name": raw_name,
            "company_name": raw_name,
            "website": website,
            "description": f"{desc}. Free tier allocation: {free_tier}",
            "pricing_model": pricing_model,
            "source_name": "Free AI APIs Directory",
            "source_url": doc_url or website,
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        }
        products.append(record)

    return products


def parse_free_ai_tools_directory(content: str) -> List[Dict[str, Any]]:
    """Parse developer AI tools, coding copilots, and frameworks from the Free AI Tools markdown."""
    products = []
    # Match markdown table lines with tool names and descriptions:
    # | [Tool Name](#anchor) | Models/Specs | Free Tier Limit | Credit Card |
    pattern = re.compile(r"\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|")

    for line in content.splitlines():
        match = pattern.search(line)
        if not match:
            continue

        name = match.group(1).strip()
        col2 = match.group(3).strip()
        col3 = match.group(4).strip()
        col4 = match.group(5).strip()

        if name.lower() in ("provider", "ide", "tool", "platform", "model", "layer"):
            continue

        combined_desc = f"{col2}. Free tier: {col3}."
        pricing_model = determine_pricing_model(col3) or "FREEMIUM"

        record = {
            "schemaVersion": "1.0",
            "recordType": "PRODUCT",
            "product_name": name,
            "company_name": name,
            "website": f"https://github.com/ShaikhWarsi/free-ai-tools#{re.sub(r'[^a-zA-Z0-9-]', '', name.lower())}",
            "description": combined_desc,
            "pricing_model": pricing_model,
            "source_name": "Free AI Tools Directory",
            "source_url": "https://github.com/ShaikhWarsi/free-ai-tools",
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        }
        products.append(record)

    return products


def parse_openrouter_models(data: Any) -> List[Dict[str, Any]]:
    """Parse AI models and products from OpenRouter's official API."""
    products = []
    if isinstance(data, list):
        models = data
    elif isinstance(data, dict):
        models = data.get("data", [])
    else:
        models = []

    for m in models:
        raw_name = m.get("name") or m.get("id", "")
        model_id = m.get("id", "")

        # Extract provider/company from model ID prefix
        company = None
        if "/" in model_id:
            raw_comp = model_id.split("/")[0]
            company = raw_comp.replace("-", " ").title()

        # Extract pricing model
        pricing = m.get("pricing", {}) or {}
        try:
            prompt_cost = float(pricing.get("prompt", 0) or 0)
            completion_cost = float(pricing.get("completion", 0) or 0)
        except (ValueError, TypeError):
            prompt_cost, completion_cost = 0.0, 0.0

        if ":free" in model_id or (prompt_cost == 0 and completion_cost == 0):
            pricing_model = "FREE"
        else:
            pricing_model = "PAID"

        desc = clean_text(m.get("description", ""))
        source_url = f"https://openrouter.ai/models/{model_id}"

        record = {
            "schemaVersion": "1.0",
            "recordType": "PRODUCT",
            "product_name": clean_text(raw_name) or model_id,
            "company_name": company,
            "website": source_url,
            "description": desc,
            "pricing_model": pricing_model,
            "source_name": "OpenRouter",
            "source_url": source_url,
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        }
        products.append(record)

    return products


def parse_huggingface_models(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parse top open-source AI foundation models and products from Hugging Face's official API."""
    products = []
    for m in models:
        model_id = m.get("id") or m.get("modelId", "")
        if not model_id:
            continue

        # Extract provider/organization and model name
        if "/" in model_id:
            parts = model_id.split("/")
            company = parts[0].replace("-", " ").title()
            name = parts[1]
        else:
            company = "Hugging Face"
            name = model_id

        pipeline = m.get("pipeline_tag") or "AI Model"
        downloads = m.get("downloads", 0)
        likes = m.get("likes", 0)
        desc = f"Open-weights AI model for {pipeline} (Downloads: {downloads:,}, Likes: {likes:,})."

        # Open-weights models on Hugging Face are free/open-source
        pricing_model = "FREE"
        source_url = f"https://huggingface.co/{model_id}"

        record = {
            "schemaVersion": "1.0",
            "recordType": "PRODUCT",
            "product_name": model_id,
            "company_name": company,
            "website": source_url,
            "description": desc,
            "pricing_model": pricing_model,
            "source_name": "Hugging Face",
            "source_url": source_url,
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        }
        products.append(record)

    return products


async def crawl_products(
    target_count: int = DEFAULT_TARGET_PRODUCTS,
) -> List[Dict[str, Any]]:
    """Crawl AI products, models, and tools across verified public directories and APIs.

    Saves raw results to data/raw/products.json and processed records to data/processed/products.csv.
    """
    logger.info("Starting AI product crawler with target of %d products...", target_count)

    products: List[Dict[str, Any]] = []
    seen_keys = set()

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        # 1. Fetch developer AI API products (gives FREEMIUM and FREE models)
        logger.info("Fetching products from Free AI APIs directory: %s", FREE_AI_APIS_DIRECTORY_URL)
        apis_content = await fetch_text(session, FREE_AI_APIS_DIRECTORY_URL)
        if apis_content:
            api_products = parse_free_ai_apis_directory(apis_content)
            logger.info("Parsed %d products from Free AI APIs directory.", len(api_products))
            for p in api_products:
                k = normalize_product_key(p["product_name"], p.get("company_name"))
                if k not in seen_keys:
                    seen_keys.add(k)
                    products.append(p)
                    if len(products) >= target_count:
                        break

        # 2. Fetch developer tools if target not reached (IDEs, vector DBs, assistants)
        if len(products) < target_count:
            logger.info("Fetching products from Free AI Tools directory: %s", FREE_AI_TOOLS_DIRECTORY_URL)
            tools_content = await fetch_text(session, FREE_AI_TOOLS_DIRECTORY_URL)
            if tools_content:
                tools_products = parse_free_ai_tools_directory(tools_content)
                logger.info("Parsed %d products from Free AI Tools directory.", len(tools_products))
                for p in tools_products:
                    k = normalize_product_key(p["product_name"], p.get("company_name"))
                    if k not in seen_keys:
                        seen_keys.add(k)
                        products.append(p)
                        if len(products) >= target_count:
                            break

        # 3. Fetch from OpenRouter models API (gives extensive list of verified PAID/FREE AI models)
        if len(products) < target_count:
            logger.info("Fetching products from OpenRouter API: %s", OPENROUTER_MODELS_API_URL)
            openrouter_data = await fetch_json(session, OPENROUTER_MODELS_API_URL)
            if openrouter_data and isinstance(openrouter_data, dict):
                or_products = parse_openrouter_models(openrouter_data)
                logger.info("Parsed %d products from OpenRouter.", len(or_products))
                for p in or_products:
                    k = normalize_product_key(p["product_name"], p.get("company_name"))
                    if k not in seen_keys:
                        seen_keys.add(k)
                        products.append(p)
                        if len(products) >= target_count:
                            break

        # 4. Fetch top open-source AI models from Hugging Face API to reach bulk target
        if len(products) < target_count:
            logger.info("Fetching models from Hugging Face API: %s", HUGGINGFACE_MODELS_API_URL)
            hf_data = await fetch_json(session, HUGGINGFACE_MODELS_API_URL)
            if hf_data and isinstance(hf_data, list):
                hf_products = parse_huggingface_models(hf_data)
                logger.info("Parsed %d models from Hugging Face.", len(hf_products))
                for p in hf_products:
                    k = normalize_product_key(p["product_name"], p.get("company_name"))
                    if k not in seen_keys:
                        seen_keys.add(k)
                        products.append(p)
                        if len(products) >= target_count:
                            break

    logger.info("Successfully collected and deduplicated %d AI products.", len(products))

    # Save to disk via centralized ExportService
    save_product_outputs(products)

    return products


def save_product_outputs(products: List[Dict[str, Any]]) -> None:
    """Save collected products to data/raw/products.json and data/processed/products.csv via ExportService."""
    export_service.export_dataset(products, "products")
    logger.info("Saved %d product records via ExportService.", len(products))
