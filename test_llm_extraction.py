"""Test script to process a maximum of 5 news articles and 5 jobs using the LLM Extraction Engine."""

import asyncio
import json
from pathlib import Path
import sys

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from src.config import PROCESSED_DATA_DIR, RAW_DATA_DIR
from src.extractors.llm_extractor import extract_batch_jobs, extract_batch_news
from src.services.llm_service import LLMService
from src.utils.logger import get_logger

logger = get_logger("test_llm_extraction")


async def main():
    print("=" * 70)
    print("LLM EXTRACTION ENGINE - INITIAL TEST RUN (MAX 5 NEWS, 5 JOBS)")
    print("=" * 70)

    llm_service = LLMService()

    # Check key status
    print("\n[Provider Configuration Status]")
    print(f"  - Gemini API Key  : {'Configured' if llm_service.gemini_key else 'Missing'}")
    print(f"  - Groq API Key    : {'Configured' if llm_service.groq_key else 'Missing'}")
    print(f"  - DeepSeek API Key: {'Configured' if llm_service.deepseek_key else 'Missing'}")

    if not llm_service.has_configured_provider():
        print("\n" + "!" * 70)
        print("ATTENTION: No LLM API keys found in .env or environment!")
        print("To enable live extraction, set at least one of:")
        print("  GEMINI_API_KEY=your_key_here")
        print("  GROQ_API_KEY=your_key_here")
        print("  DEEPSEEK_API_KEY=your_key_here")
        print("in your .env file.")
        print("!" * 70 + "\n")
        return

    # 1. Process News
    news_file = RAW_DATA_DIR / "news.json"
    if news_file.exists():
        with open(news_file, "r", encoding="utf-8") as f:
            news_items = json.load(f)
        print(f"\nProcessing up to 5 news articles out of {len(news_items)} total...")
        extracted_news = await extract_batch_news(news_items, max_items=5, llm_service=llm_service)
        print(f"Successfully extracted {len(extracted_news)} news items.")
        if extracted_news:
            print("\nSample Extracted News Record:")
            print(json.dumps(extracted_news[0], indent=2))
    else:
        print("No raw news file found at data/raw/news.json. Run main.py first.")

    # 2. Process Jobs
    jobs_file = RAW_DATA_DIR / "jobs.json"
    if jobs_file.exists():
        with open(jobs_file, "r", encoding="utf-8") as f:
            job_items = json.load(f)
        print(f"\nProcessing up to 5 job postings out of {len(job_items)} total...")
        extracted_jobs = await extract_batch_jobs(job_items, max_items=5, llm_service=llm_service)
        print(f"Successfully extracted {len(extracted_jobs)} job items.")
        if extracted_jobs:
            print("\nSample Extracted Job Record:")
            print(json.dumps(extracted_jobs[0], indent=2))
    else:
        print("No raw jobs file found at data/raw/jobs.json. Run main.py first.")

    print("\n" + "=" * 70)
    print("Extraction outputs saved to:")
    print("  - data/processed/extracted_news.json")
    print("  - data/processed/extracted_jobs.json")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
