"""Main entry point and orchestrator for AI Intelligence Ingestion Pipeline.

Orchestrates the complete ingestion lifecycle asynchronously:
1. Ingestion: Runs all 5 crawlers concurrently (arXiv, Startups, Products, News, Jobs).
2. Freshness Validation: Evaluates 24-hour freshness for News and Jobs.
3. LLM Extraction Engine: Extracts structured intelligence via multi-provider fallback (Gemini -> Groq -> DeepSeek).
4. Entity Resolution & Canonicalization: Resolves entities across datasets and records lineage logs.
5. Centralized Artifact Export: Exports all datasets consistently to JSON and CSV via ExportService.
6. Execution Summary: Generates a comprehensive execution audit and health report.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from src.config import PROCESSED_DATA_DIR, RAW_DATA_DIR
from src.crawlers.arxiv_crawler import crawl_arxiv_papers
from src.crawlers.jobs_crawler import crawl_jobs
from src.crawlers.news_crawler import crawl_news
from src.crawlers.product_crawler import crawl_products
from src.crawlers.startup_crawler import crawl_startups
from src.extractors.llm_extractor import ExtractionStats, extract_batch_jobs, extract_batch_news
from src.processors.date_parser import is_within_last_24_hours
from src.processors.entity_resolution import resolve_all_intelligence_entities
from src.services.export_service import export_service
from src.services.llm_service import LLMService
from src.utils.logger import get_logger

logger = get_logger("orchestrator")


async def execute_crawler_task(
    name: str,
    crawler_coro: Any,
    errors_list: List[str],
) -> Tuple[str, List[Dict[str, Any]], str]:
    """Execute a single crawler coroutine safely, guarding against pipeline termination on failure."""
    try:
        records = await crawler_coro
        return name, records, "SUCCESS"
    except Exception as exc:
        err_msg = f"Crawler '{name}' failed: {exc}"
        logger.error(err_msg, exc_info=True)
        errors_list.append(err_msg)
        return name, [], "FAILED"


async def run_pipeline(
    target_count: int = 1000,
    llm_sample_size: int = 5,
    skip_crawlers_if_raw_exists: bool = False,
) -> Dict[str, Any]:
    """Execute the end-to-end intelligence ingestion pipeline."""
    start_time = time.time()
    errors: List[str] = []
    warnings: List[str] = []

    print("\n" + "=" * 80)
    print("      AI INTELLIGENCE INGESTION PIPELINE - END-TO-END EXECUTION")
    print(f"      Started at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # STAGE 1: Concurrent Crawler Ingestion
    # -------------------------------------------------------------------------
    print("\n[STAGE 1/4] Running Ingestion Crawlers Concurrently...")

    crawler_tasks = [
        execute_crawler_task("Research Papers", crawl_arxiv_papers(target_count=target_count), errors),
        execute_crawler_task("Startups", crawl_startups(target_count=target_count), errors),
        execute_crawler_task("Products", crawl_products(target_count=target_count), errors),
        execute_crawler_task("News", crawl_news(), errors),
        execute_crawler_task("Jobs", crawl_jobs(), errors),
    ]

    crawler_results = await asyncio.gather(*crawler_tasks)
    datasets: Dict[str, List[Dict[str, Any]]] = {}
    crawler_status: Dict[str, str] = {}

    for name, records, status in crawler_results:
        datasets[name] = records
        crawler_status[name] = status
        print(f"  -> {name:<18}: {len(records):>4} records ({status})")

    papers = datasets.get("Research Papers", [])
    startups = datasets.get("Startups", [])
    products = datasets.get("Products", [])
    news = datasets.get("News", [])
    jobs = datasets.get("Jobs", [])

    # Export ingested datasets through the Centralized Export Service
    print("\n[STAGE 1b] Exporting Ingested Datasets via Centralized Export Service...")
    export_service.export_dataset(papers, "research_papers")
    export_service.export_dataset(startups, "startups")
    export_service.export_dataset(products, "products")
    export_service.export_dataset(news, "news")
    export_service.export_dataset(jobs, "jobs")

    # -------------------------------------------------------------------------
    # STAGE 2: 24-Hour Freshness Filtering & Verification
    # -------------------------------------------------------------------------
    print("\n[STAGE 2/4] Validating 24-Hour Freshness Window...")
    fresh_news = [item for item in news if is_within_last_24_hours(item.get("published_date", ""))]
    fresh_jobs = [item for item in jobs if is_within_last_24_hours(item.get("published_date", ""))]

    print(f"  -> News Freshness : {len(fresh_news)} / {len(news)} articles verified within past 24h")
    print(f"  -> Jobs Freshness : {len(fresh_jobs)} / {len(jobs)} postings verified within past 24h")

    if len(fresh_news) < len(news):
        warnings.append(f"{len(news) - len(fresh_news)} news items were outside the strict 24h window.")
    if len(fresh_jobs) < len(jobs):
        warnings.append(f"{len(jobs) - len(fresh_jobs)} job postings were outside the strict 24h window.")

    # -------------------------------------------------------------------------
    # STAGE 3: Multi-Provider LLM Extraction Engine
    # -------------------------------------------------------------------------
    print(f"\n[STAGE 3/4] Running LLM Extraction Engine (Gemini -> Groq -> DeepSeek)...")
    llm_service = LLMService()
    extraction_stats = ExtractionStats()

    news_target = fresh_news if fresh_news else news
    jobs_target = fresh_jobs if fresh_jobs else jobs

    print(f"  -> Extracting structured intelligence from top {llm_sample_size} fresh news articles...")
    extracted_news = await extract_batch_news(
        news_target,
        max_items=llm_sample_size,
        llm_service=llm_service,
        stats=extraction_stats,
    )

    print(f"  -> Extracting structured intelligence from top {llm_sample_size} fresh job postings...")
    extracted_jobs = await extract_batch_jobs(
        jobs_target,
        max_items=llm_sample_size,
        llm_service=llm_service,
        stats=extraction_stats,
    )

    print(f"  -> LLM Extraction complete: {extraction_stats.succeeded}/{extraction_stats.attempted} successful.")
    for prov, count in extraction_stats.providers.items():
        print(f"     Provider {prov}: {count} extractions")
    if extraction_stats.fallbacks > 0:
        print(f"     Fallback activations: {extraction_stats.fallbacks}")

    # -------------------------------------------------------------------------
    # STAGE 4: Entity Resolution & Canonicalization
    # -------------------------------------------------------------------------
    print("\n[STAGE 4/4] Executing Entity Resolution & Canonicalization...")
    resolver, resolved_datasets = resolve_all_intelligence_entities(
        startups=startups,
        products=products,
        papers=papers,
        export_csv=True,
    )

    mapping_df = resolver.get_mapping_logs_df()
    unique_canonical_count = mapping_df["canonical_entity_id"].nunique()
    type_counts = mapping_df["canonical_entity_id"].apply(lambda x: x.split("_")[1]).value_counts().to_dict()
    method_counts = mapping_df["matching_method"].value_counts().to_dict()

    print(f"  -> Total Entity Resolution Events : {len(mapping_df)}")
    print(f"  -> Unique Canonical Entities      : {unique_canonical_count}")
    for method, cnt in method_counts.items():
        print(f"     - Method {method:<22}: {cnt}")

    # -------------------------------------------------------------------------
    # STAGE 5: Comprehensive Execution Summary Report
    # -------------------------------------------------------------------------
    elapsed = time.time() - start_time
    print("\n" + "=" * 80)
    print("                     PIPELINE EXECUTION SUMMARY REPORT")
    print("=" * 80)

    # 1. Ingestion Table
    print("\n1. Ingestion & Crawler Performance:")
    print(f"   {'Crawler Module':<22} | {'Status':<10} | {'Records Ingested':<16} | {'Fresh (24h)'}")
    print("   " + "-" * 65)
    print(f"   {'Research Papers':<22} | {crawler_status.get('Research Papers', 'N/A'):<10} | {len(papers):<16} | N/A (Catalog)")
    print(f"   {'Startups':<22} | {crawler_status.get('Startups', 'N/A'):<10} | {len(startups):<16} | N/A (Catalog)")
    print(f"   {'Products':<22} | {crawler_status.get('Products', 'N/A'):<10} | {len(products):<16} | N/A (Catalog)")
    print(f"   {'News':<22} | {crawler_status.get('News', 'N/A'):<10} | {len(news):<16} | {len(fresh_news)}")
    print(f"   {'Jobs':<22} | {crawler_status.get('Jobs', 'N/A'):<10} | {len(jobs):<16} | {len(fresh_jobs)}")
    print(f"   {'TOTAL RECORDS':<22} | {'SUCCESS':<10} | {len(papers)+len(startups)+len(products)+len(news)+len(jobs):<16} |")

    # 2. LLM Extraction Table
    print("\n2. LLM Extraction Engine Metrics:")
    print(f"   Total Attempted Extractions : {extraction_stats.attempted}")
    print(f"   Successfully Validated      : {extraction_stats.succeeded}")
    print(f"   Validation / Parse Failures : {extraction_stats.failed}")
    print(f"   Fallback Engine Invocations : {extraction_stats.fallbacks}")
    print(f"   Provider Distribution       : {dict(extraction_stats.providers)}")

    # 3. Entity Resolution Table
    print("\n3. Entity Resolution & Canonicalization:")
    print(f"   Total Resolution Events     : {len(mapping_df)}")
    print(f"   Unique Canonical Entities   : {unique_canonical_count}")
    print(f"   - Companies (ent_comp_)     : {type_counts.get('comp', 0)}")
    print(f"   - Products (ent_prod_)      : {type_counts.get('prod', 0)}")
    print(f"   - Research Papers (ent_rese_): {type_counts.get('rese', 0)}")
    print(f"   Matching Methods Breakdown  :")
    for m, c in method_counts.items():
        print(f"     * {m:<26}: {c}")

    # 4. Artifact Paths
    artifacts = [
        RAW_DATA_DIR / "research_papers.json",
        PROCESSED_DATA_DIR / "research_papers.csv",
        RAW_DATA_DIR / "startups.json",
        PROCESSED_DATA_DIR / "startups.csv",
        RAW_DATA_DIR / "products.json",
        PROCESSED_DATA_DIR / "products.csv",
        RAW_DATA_DIR / "news.json",
        PROCESSED_DATA_DIR / "news.csv",
        RAW_DATA_DIR / "jobs.json",
        PROCESSED_DATA_DIR / "jobs.csv",
        PROCESSED_DATA_DIR / "extracted_news.json",
        PROCESSED_DATA_DIR / "extracted_jobs.json",
        PROCESSED_DATA_DIR / "entity_mapping_log.csv",
    ]

    print("\n4. Verified Generated Artifacts:")
    for art in artifacts:
        status_mark = "[EXISTS]" if art.exists() else "[MISSING]"
        size_kb = f"{art.stat().st_size / 1024:.1f} KB" if art.exists() else "0 KB"
        print(f"   {status_mark} {art.relative_to(Path.cwd())} ({size_kb})")

    # 5. Errors and Warnings
    print("\n5. Errors & Warnings:")
    if errors:
        print(f"   Errors Encountered ({len(errors)}):")
        for err in errors:
            print(f"     [!] {err}")
    else:
        print("   Errors Encountered: None (Pipeline completed cleanly).")

    if warnings:
        print(f"   Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"     [*] {w}")
    else:
        print("   Warnings: None.")

    print(f"\nExecution Duration: {elapsed:.2f} seconds.")
    print("=" * 80 + "\n")

    return {
        "status": "SUCCESS" if not errors else "PARTIAL_SUCCESS",
        "duration_seconds": elapsed,
        "datasets": {k: len(v) for k, v in datasets.items()},
        "freshness": {"news": len(fresh_news), "jobs": len(fresh_jobs)},
        "llm_stats": extraction_stats.to_dict(),
        "entity_resolution": {
            "events": len(mapping_df),
            "canonical_entities": unique_canonical_count,
            "methods": method_counts,
        },
        "errors": errors,
        "warnings": warnings,
    }


def main() -> None:
    """Main CLI entrypoint."""
    try:
        asyncio.run(run_pipeline(target_count=1000, llm_sample_size=5))
    except KeyboardInterrupt:
        logger.warning("Pipeline execution cancelled by user.")
    except Exception as exc:
        logger.critical("Fatal exception during pipeline run: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
