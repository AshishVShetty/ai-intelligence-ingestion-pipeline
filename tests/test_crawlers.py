"""Unit tests for the ingestion pipeline crawlers, schemas, date filtering, and deduplication."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from src.config import PROCESSED_DATA_DIR, RAW_DATA_DIR
from src.crawlers.arxiv_crawler import extract_github_url, normalize_arxiv_id, reconstruct_abstract
from src.crawlers.jobs_crawler import classify_role_family, infer_remote_status
from src.crawlers.product_crawler import (
    determine_pricing_model,
    normalize_product_key,
    parse_huggingface_models,
    parse_openrouter_models,
)
from src.crawlers.startup_crawler import normalize_company_name
from src.extractors.schemas import (
    JobSchema,
    NewsSchema,
    ProductSchema,
    ResearchPaperSchema,
    StartupSchema,
)
from src.processors.date_parser import is_within_last_24_hours, parse_to_utc, parse_to_utc_iso
from src.processors.deduplication import deduplicate_by_url, normalize_url


class TestCrawlersAndProcessors(unittest.TestCase):
    """Test suite validating ingestion schemas, date parsing, 24h filtering, and deduplication."""

    def test_pricing_model_heuristic(self):
        """Verify that pricing model detection maps to expected enum strings."""
        self.assertEqual(determine_pricing_model("100% free open-source"), "FREE")
        self.assertEqual(determine_pricing_model("Free tier with 1,000 requests/day"), "FREEMIUM")
        self.assertEqual(determine_pricing_model("$20/mo subscription"), "PAID")
        self.assertEqual(determine_pricing_model("Custom pricing, contact enterprise sales"), "ENTERPRISE")
        self.assertIsNone(determine_pricing_model(None))

    def test_normalization_functions(self):
        """Verify deduplication normalization keys."""
        self.assertEqual(normalize_company_name("OpenAI, Inc."), "openai")
        self.assertEqual(normalize_product_key("GPT-4o", "OpenAI"), "openai:gpt4o")

    def test_date_parsing_and_utc_normalization(self):
        """Verify various date formats correctly normalize to UTC."""
        # RFC 2822
        dt_rfc = parse_to_utc("Sat, 21 Nov 2026 21:37:10 +0000")
        self.assertIsNotNone(dt_rfc)
        self.assertEqual(dt_rfc.tzinfo, timezone.utc)
        self.assertEqual(dt_rfc.year, 2026)

        # ISO 8601 with timezone offset (-05:00)
        dt_iso = parse_to_utc("2026-11-21T15:03:37-05:00")
        self.assertIsNotNone(dt_iso)
        self.assertEqual(dt_iso.tzinfo, timezone.utc)
        self.assertEqual(dt_iso.hour, 20)  # 15:03 -05:00 is 20:03 UTC

        # UNIX epoch in seconds
        dt_epoch = parse_to_utc(1795319723)
        self.assertIsNotNone(dt_epoch)
        self.assertEqual(dt_epoch.tzinfo, timezone.utc)

        # Invalid string
        self.assertIsNone(parse_to_utc("not-a-valid-date"))
        self.assertIsNone(parse_to_utc(None))
        self.assertIsNone(parse_to_utc(""))

    def test_24_hour_freshness_filter(self):
        """Verify that only dates within the past 24 hours pass validation."""
        ref_now = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)

        # 2 hours ago -> should pass
        dt_recent = ref_now - timedelta(hours=2)
        self.assertTrue(is_within_last_24_hours(dt_recent, reference_time=ref_now))

        # Exactly 23 hours ago -> should pass
        dt_23h = ref_now - timedelta(hours=23)
        self.assertTrue(is_within_last_24_hours(dt_23h, reference_time=ref_now))

        # 25 hours ago -> must be rejected
        dt_old = ref_now - timedelta(hours=25)
        self.assertFalse(is_within_last_24_hours(dt_old, reference_time=ref_now))

        # 5 days ago -> must be rejected
        dt_ancient = ref_now - timedelta(days=5)
        self.assertFalse(is_within_last_24_hours(dt_ancient, reference_time=ref_now))

        # Future within 30 min tolerance -> should pass
        dt_slight_future = ref_now + timedelta(minutes=15)
        self.assertTrue(is_within_last_24_hours(dt_slight_future, reference_time=ref_now))

        # Far future (2 hours ahead) -> must be rejected
        dt_far_future = ref_now + timedelta(hours=2)
        self.assertFalse(is_within_last_24_hours(dt_far_future, reference_time=ref_now))

    def test_url_deduplication(self):
        """Verify URL normalization and duplicate removal."""
        url1 = "https://example.com/article?utm_source=twitter&utm_medium=social"
        url2 = "https://example.com/article"
        url3 = "https://example.com/article/"
        url4 = "https://example.com/different-article"

        self.assertEqual(normalize_url(url1), normalize_url(url2))
        self.assertEqual(normalize_url(url2), normalize_url(url3))
        self.assertNotEqual(normalize_url(url1), normalize_url(url4))

        records = [
            {"title": "A", "url": url1},
            {"title": "B", "url": url2},
            {"title": "C", "url": url3},
            {"title": "D", "url": url4},
        ]
        deduped = deduplicate_by_url(records, url_key="url")
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0]["title"], "A")
        self.assertEqual(deduped[1]["title"], "D")

    def test_job_helpers(self):
        """Verify role classification and remote status inference."""
        self.assertEqual(classify_role_family("Senior Machine Learning Engineer"), "Machine Learning")
        self.assertEqual(classify_role_family("AI Research Scientist"), "AI Research")
        self.assertEqual(classify_role_family("Lead Data Analyst"), "Data Science")
        self.assertEqual(classify_role_family("Backend Python Developer"), "Software Engineering")
        self.assertEqual(classify_role_family("Staff Product Manager, GenAI"), "Product & Management")

        self.assertEqual(infer_remote_status(True), "REMOTE")
        self.assertEqual(infer_remote_status(False, "Hybrid - Berlin"), "HYBRID")
        self.assertEqual(infer_remote_status(False, "On-site, London"), "ONSITE")

    def test_news_output_and_freshness(self):
        """Verify news output exists and all records conform to schema within 24h of collection."""
        raw_path = RAW_DATA_DIR / "news.json"
        self.assertTrue(raw_path.exists(), "news.json should exist")

        with open(raw_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertGreater(len(data), 0, "news.json should contain articles")
        for item in data:
            validated = NewsSchema(**item)
            self.assertEqual(validated.recordType, "NEWS")
            self.assertTrue(validated.title)
            self.assertTrue(validated.url)
            pub_dt = parse_to_utc(validated.published_date)
            collected_dt = parse_to_utc(validated.collectedAt)
            self.assertIsNotNone(pub_dt)
            self.assertIsNotNone(collected_dt)
            # Ensure article was published within 24 hours of ingestion
            self.assertTrue(is_within_last_24_hours(pub_dt, reference_time=collected_dt))

    def test_jobs_output_and_freshness(self):
        """Verify jobs output exists and all records conform to schema within 24h of collection."""
        raw_path = RAW_DATA_DIR / "jobs.json"
        self.assertTrue(raw_path.exists(), "jobs.json should exist")

        with open(raw_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertGreater(len(data), 0, "jobs.json should contain jobs")
        for item in data:
            validated = JobSchema(**item)
            self.assertEqual(validated.recordType, "JOB")
            self.assertTrue(validated.job_title)
            self.assertTrue(validated.company)
            self.assertTrue(validated.url)
            self.assertIn(validated.remote_status, ["REMOTE", "HYBRID", "ONSITE"])
            self.assertIn(
                validated.role_family,
                ["AI Research", "Machine Learning", "Data Science", "Software Engineering", "Product & Management", "Other"],
            )
            pub_dt = parse_to_utc(validated.published_date)
            collected_dt = parse_to_utc(validated.collectedAt)
            self.assertIsNotNone(pub_dt)
            self.assertIsNotNone(collected_dt)
            # Ensure job was published within 24 hours of ingestion
            self.assertTrue(is_within_last_24_hours(pub_dt, reference_time=collected_dt))

    def test_arxiv_id_normalization_and_github_extraction(self):
        """Verify arXiv ID version stripping and GitHub URL extraction."""
        self.assertEqual(normalize_arxiv_id("http://arxiv.org/abs/2301.12345v2"), "http://arxiv.org/abs/2301.12345")
        self.assertEqual(normalize_arxiv_id("2301.12345v1"), "2301.12345")
        self.assertEqual(normalize_arxiv_id("2301.12345"), "2301.12345")

        # Valid GitHub repo extraction with .git stripping
        text_with_repo = "Official code available at https://github.com/meta-llama/llama3.git in PyTorch."
        self.assertEqual(extract_github_url(text_with_repo), "https://github.com/meta-llama/llama3")

        # Generic non-repo GitHub paths must be ignored
        self.assertIsNone(extract_github_url("Visit https://github.com/features/actions for CI."))
        self.assertIsNone(extract_github_url("No link here."))

        # Abstract reconstruction from inverted index
        inv_index = {"Large": [0], "language": [1], "models": [2], "are": [3], "effective.": [4]}
        self.assertEqual(reconstruct_abstract(inv_index), "Large language models are effective.")
        self.assertEqual(reconstruct_abstract(None), "")
        self.assertEqual(reconstruct_abstract({}), "")

    def test_huggingface_model_parsing(self):
        """Verify parsing and schema adherence for Hugging Face open-source models."""
        raw_hf_models = [
            {
                "id": "meta-llama/Llama-3-70B-Instruct",
                "pipeline_tag": "text-generation",
                "downloads": 1542000,
                "likes": 28400,
            },
            {
                "modelId": "stabilityai/stable-diffusion-3-medium",
                "pipeline_tag": "text-to-image",
                "downloads": 820000,
                "likes": 12000,
            },
        ]
        parsed = parse_huggingface_models(raw_hf_models)
        self.assertEqual(len(parsed), 2)
        for item in parsed:
            validated = ProductSchema(**item)
            self.assertEqual(validated.recordType, "PRODUCT")
            self.assertEqual(validated.pricing_model, "FREE")
            self.assertEqual(validated.source_name, "Hugging Face")
            self.assertTrue(validated.website.startswith("https://huggingface.co/"))

        self.assertEqual(parsed[0]["company_name"], "Meta Llama")
        self.assertEqual(parsed[1]["company_name"], "Stabilityai")

    def test_openrouter_model_parsing(self):
        """Verify pricing model classification for OpenRouter models."""
        mock_or_models = [
            {
                "id": "google/gemini-2.0-flash-exp:free",
                "name": "Google: Gemini 2.0 Flash (Free)",
                "description": "High-speed multimodal model.",
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "id": "anthropic/claude-3.5-sonnet",
                "name": "Anthropic: Claude 3.5 Sonnet",
                "description": "Top tier reasoning model.",
                "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            },
        ]
        parsed = parse_openrouter_models(mock_or_models)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["pricing_model"], "FREE")
        self.assertEqual(parsed[1]["pricing_model"], "PAID")
        self.assertEqual(parsed[0]["company_name"], "Google")
        self.assertEqual(parsed[1]["company_name"], "Anthropic")

    def test_startup_deduplication_across_feeds(self):
        """Verify deduplication normalization prevents duplicate startup entries across feeds."""
        company_a = "Anthropic, PBC"
        company_b = "anthropic"
        self.assertEqual(normalize_company_name(company_a), normalize_company_name(company_b))



if __name__ == "__main__":
    unittest.main()
