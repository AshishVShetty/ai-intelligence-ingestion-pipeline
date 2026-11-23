"""Unit tests for ExportService, Retry utilities, and GitHubService."""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

import pandas as pd

from src.services.export_service import ExportService, flatten_record_for_csv
from src.services.github_service import GitHubService
from src.utils.retry import async_retry, calculate_backoff, with_retry


class TestExportService(unittest.TestCase):
    """Test suite for ExportService serialization and flattening."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.raw_dir = Path(self.temp_dir.name) / "raw"
        self.processed_dir = Path(self.temp_dir.name) / "processed"
        self.service = ExportService(raw_dir=self.raw_dir, processed_dir=self.processed_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_flatten_record_for_csv(self):
        """Test flattening of nested lists, dicts, datetimes, and nulls."""
        record = {
            "title": "Deep Learning Models",
            "authors": ["Alice Smith", "Bob Jones"],
            "published_at": datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            "metadata": {"citations": 42},
            "missing_field": None,
        }
        flat = flatten_record_for_csv(record)

        self.assertEqual(flat["title"], "Deep Learning Models")
        self.assertEqual(flat["authors"], "Alice Smith; Bob Jones")
        self.assertEqual(flat["published_at"], "2026-01-15T12:00:00+00:00")
        self.assertIn("citations", flat["metadata"])
        self.assertEqual(flat["missing_field"], "")

    def test_export_json_and_csv(self):
        """Test file creation, encoding, and schema preservation."""
        records = [
            {"id": "1", "name": "Tool A", "tags": ["nlp", "llm"], "price": 0.0},
            {"id": "2", "name": "Tool B", "tags": ["cv"], "price": 19.99},
        ]
        raw_path, csv_path = self.service.export_dataset(records, "test_tools")

        self.assertTrue(raw_path.exists())
        self.assertTrue(csv_path.exists())

        # Validate JSON content
        with open(raw_path, "r", encoding="utf-8") as f:
            loaded_json = json.load(f)
        self.assertEqual(len(loaded_json), 2)
        self.assertEqual(loaded_json[0]["name"], "Tool A")

        # Validate CSV content
        df = pd.read_csv(csv_path)
        self.assertEqual(len(df), 2)
        self.assertEqual(df["tags"].iloc[0], "nlp; llm")
        self.assertListEqual(list(df.columns), ["id", "name", "tags", "price"])


class TestRetryUtility(unittest.IsolatedAsyncioTestCase):
    """Test suite for async_retry and backoff calculations."""

    def test_calculate_backoff(self):
        """Test backoff calculation with and without retry_after."""
        b1 = calculate_backoff(attempt=1, initial_delay=1.0, jitter=False)
        self.assertEqual(b1, 1.0)

        b2 = calculate_backoff(attempt=2, initial_delay=1.0, backoff_factor=2.0, jitter=False)
        self.assertEqual(b2, 2.0)

        b_retry_after = calculate_backoff(attempt=1, retry_after=5.5)
        self.assertEqual(b_retry_after, 5.5)

    async def test_successful_execution_without_retry(self):
        """Test that a healthy coroutine executes without retrying."""
        calls = 0

        async def healthy_op(x: int) -> int:
            nonlocal calls
            calls += 1
            return x * 2

        res = await async_retry(healthy_op, 5, max_attempts=3, initial_delay=0.01)
        self.assertEqual(res, 10)
        self.assertEqual(calls, 1)

    async def test_transient_failure_then_success(self):
        """Test that transient failures trigger retry and succeed."""
        attempts = 0

        async def flaky_op() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("Temporary glitch")
            return "SUCCESS"

        res = await async_retry(
            flaky_op,
            max_attempts=4,
            initial_delay=0.01,
            jitter=False,
            retryable_exceptions=(ConnectionError,),
        )
        self.assertEqual(res, "SUCCESS")
        self.assertEqual(attempts, 3)

    async def test_non_retryable_exception_aborts_immediately(self):
        """Test that non-retryable exceptions terminate without further attempts."""
        attempts = 0

        async def bad_args_op() -> None:
            nonlocal attempts
            attempts += 1
            raise ValueError("Invalid argument")

        with self.assertRaises(ValueError):
            await async_retry(bad_args_op, max_attempts=5, initial_delay=0.01)
        self.assertEqual(attempts, 1)

    async def test_retry_decorator(self):
        """Test @with_retry decorator behavior."""
        counter = 0

        @with_retry(max_attempts=3, initial_delay=0.01, jitter=False)
        async def decorated_flaky():
            nonlocal counter
            counter += 1
            if counter < 2:
                raise RuntimeError("First attempt fails")
            return "DECORATOR_SUCCESS"

        result = await decorated_flaky()
        self.assertEqual(result, "DECORATOR_SUCCESS")
        self.assertEqual(counter, 2)


class TestGitHubService(unittest.TestCase):
    """Test suite for GitHubService slug extraction."""

    def setUp(self):
        self.service = GitHubService()

    def test_extract_repo_slug(self):
        """Test slug extraction from multiple URL patterns."""
        self.assertEqual(
            self.service.extract_repo_slug("https://github.com/vllm-project/vllm"),
            "vllm-project/vllm",
        )
        self.assertEqual(
            self.service.extract_repo_slug("http://www.github.com/openai/whisper.git"),
            "openai/whisper",
        )
        self.assertIsNone(self.service.extract_repo_slug("https://google.com"))
        self.assertIsNone(self.service.extract_repo_slug(""))


if __name__ == "__main__":
    unittest.main()
