"""Unit tests for the LLM Service and Extraction Engine.

Tests:
- Provider fallback chain (Gemini -> Groq -> DeepSeek)
- Invalid JSON handling and fallback
- Payload size bounding / truncation
- Missing API keys handling
- Rate limit (HTTP 429) exponential backoff and retry limit
"""

import asyncio
import json
from pathlib import Path
import sys
from typing import Any
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from src.extractors.schemas import ExtractedJobSchema, ExtractedNewsSchema
from src.services.llm_service import LLMService, bound_payload, clean_json_markdown


class MockResponse:
    """Mock aiohttp HTTP response context manager."""

    def __init__(self, status: int, data: Any):
        self.status = status
        self._data = data

    async def json(self):
        if isinstance(self._data, (dict, list)):
            return self._data
        return json.loads(self._data)

    async def text(self):
        if isinstance(self._data, str):
            return self._data
        return json.dumps(self._data)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class TestLLMService(unittest.IsolatedAsyncioTestCase):
    """Test suite for multi-provider fallback and safeguards."""

    def test_clean_json_markdown(self):
        """Verify markdown extraction strips code fences and conversational preamble."""
        raw_markdown = "Here is the JSON:\n```json\n{\"title\": \"AI Breakthrough\"}\n```\nHope this helps!"
        cleaned = clean_json_markdown(raw_markdown)
        self.assertEqual(cleaned, '{"title": "AI Breakthrough"}')
        self.assertEqual(json.loads(cleaned)["title"], "AI Breakthrough")

    def test_bound_payload_truncation(self):
        """Verify long input strings are bounded with truncation notice."""
        large_text = "A" * 12000
        bounded = bound_payload(large_text, max_chars=8000)
        self.assertLessEqual(len(bounded), 8100)
        self.assertIn("[Warning: Input truncated due to size limits]", bounded)

        normal_text = "Small prompt"
        self.assertEqual(bound_payload(normal_text, max_chars=8000), normal_text)

    def test_missing_api_keys(self):
        """Verify service detects missing keys and reports configuration status."""
        empty_service = LLMService(gemini_key="", groq_key="", deepseek_key="")
        self.assertFalse(empty_service.has_configured_provider())

        partial_service = LLMService(gemini_key="", groq_key="gsk_test", deepseek_key="")
        self.assertTrue(partial_service.has_configured_provider())

    async def test_provider_fallback_gemini_to_groq(self):
        """Verify fallback from failing Gemini to working Groq."""
        service = LLMService(
            gemini_key="gemini_test_key",
            groq_key="groq_test_key",
            deepseek_key="deepseek_test_key",
        )

        groq_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "title": "Groq Success Title",
                            "summary": "Processed via fallback provider.",
                            "companies_mentioned": ["Groq"],
                            "technologies_mentioned": ["Llama-3"],
                            "category": "Industry News",
                        })
                    }
                }
            ]
        }

        # Mock: Gemini returns 500 server error, Groq returns 200 OK
        def mock_post(url, *args, **kwargs):
            if "generativelanguage.googleapis.com" in url:
                return MockResponse(500, "Internal Server Error")
            elif "api.groq.com" in url:
                return MockResponse(200, groq_payload)
            return MockResponse(404, "Not Found")

        session_mock = MagicMock()
        session_mock.post.side_effect = mock_post

        result, provider, fallbacks = await service.generate_json(
            prompt="Extract news",
            session=session_mock,
            max_retries=1,
        )

        self.assertEqual(provider, "groq")
        self.assertEqual(fallbacks, 1)
        self.assertEqual(result["title"], "Groq Success Title")

    async def test_invalid_json_triggers_fallback(self):
        """Verify that invalid JSON from primary provider triggers fallback to next provider."""
        service = LLMService(
            gemini_key="gemini_test_key",
            groq_key="groq_test_key",
            deepseek_key="",
        )

        gemini_invalid_json = {
            "candidates": [
                {"content": {"parts": [{"text": "I am an AI and here is the text without valid json {"}]}}
            ]
        }

        groq_valid_json = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "job_title": "ML Engineer",
                            "company": "DeepMind",
                            "required_skills": ["Python", "PyTorch"],
                            "role_family": "Machine Learning",
                            "remote_status": "REMOTE",
                        })
                    }
                }
            ]
        }

        def mock_post(url, *args, **kwargs):
            if "generativelanguage.googleapis.com" in url:
                return MockResponse(200, gemini_invalid_json)
            elif "api.groq.com" in url:
                return MockResponse(200, groq_valid_json)
            return MockResponse(404, "Not Found")

        session_mock = MagicMock()
        session_mock.post.side_effect = mock_post

        result, provider, fallbacks = await service.generate_json(
            prompt="Extract job",
            session=session_mock,
            max_retries=1,
        )

        self.assertEqual(provider, "groq")
        self.assertEqual(fallbacks, 1)
        self.assertEqual(result["job_title"], "ML Engineer")

    async def test_rate_limit_429_backoff_and_fallback(self):
        """Verify exponential backoff on HTTP 429 and fallback when retries exhausted."""
        service = LLMService(
            gemini_key="gemini_test_key",
            groq_key="groq_test_key",
            deepseek_key="",
        )

        groq_success = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"status": "recovered"})
                    }
                }
            ]
        }

        call_counts = {"gemini": 0, "groq": 0}

        def mock_post(url, *args, **kwargs):
            if "generativelanguage.googleapis.com" in url:
                call_counts["gemini"] += 1
                return MockResponse(429, "Rate limit exceeded. Please wait.")
            elif "api.groq.com" in url:
                call_counts["groq"] += 1
                return MockResponse(200, groq_success)
            return MockResponse(404, "Not Found")

        session_mock = MagicMock()
        session_mock.post.side_effect = mock_post

        # Patch asyncio.sleep to avoid delay in tests
        with patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            result, provider, fallbacks = await service.generate_json(
                prompt="Test prompt",
                session=session_mock,
                max_retries=2,
            )

            # Gemini should have been called 1 initial + 2 retries = 3 times
            self.assertEqual(call_counts["gemini"], 3)
            # Sleep should have been called twice (backoff for 2 retries)
            self.assertEqual(sleep_mock.call_count, 2)
            # Then fallback to Groq succeeded
            self.assertEqual(provider, "groq")
            self.assertEqual(fallbacks, 1)
            self.assertEqual(result["status"], "recovered")


if __name__ == "__main__":
    unittest.main()
