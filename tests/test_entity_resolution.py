"""Unit tests and regression test suite for entity resolution and canonicalization module."""

from pathlib import Path
import sys
import unittest

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from src.processors.entity_resolution import (
    EntityResolver,
    URLClassification,
    are_names_compatible,
    classify_url,
    extract_root_domain,
    generate_canonical_id,
    normalize_entity_name,
    resolve_all_intelligence_entities,
)


class TestEntityResolution(unittest.TestCase):
    """Test suite for entity resolution, canonicalization, and deduplication rules."""

    def setUp(self):
        self.resolver = EntityResolver(fuzzy_threshold=0.88)

    # --- URL Classification & Parsing Tests ---

    def test_url_classification_categories(self):
        """Verify URL classification correctly categorizes URLs across all designated types."""
        # DIRECTORY_URL
        self.assertEqual(
            classify_url("https://github.com/ShaikhWarsi/free-ai-tools"),
            URLClassification.DIRECTORY_URL,
        )
        self.assertEqual(
            classify_url("https://www.ycombinator.com/companies/assemblyai"),
            URLClassification.DIRECTORY_URL,
        )
        self.assertEqual(
            classify_url("https://producthunt.com/products/cursor"),
            URLClassification.DIRECTORY_URL,
        )

        # DOCUMENTATION_PORTAL
        self.assertEqual(
            classify_url("https://platform.openai.com"),
            URLClassification.DOCUMENTATION_PORTAL,
        )
        self.assertEqual(
            classify_url("https://developers.openai.com/api/docs/guides/speech-to-text"),
            URLClassification.DOCUMENTATION_PORTAL,
        )
        self.assertEqual(
            classify_url("https://docs.cloud.google.com/speech-to-text/docs"),
            URLClassification.DOCUMENTATION_PORTAL,
        )
        self.assertEqual(
            classify_url("https://replicate.com/docs"),
            URLClassification.DOCUMENTATION_PORTAL,
        )

        # GENERIC_PLATFORM_URL
        self.assertEqual(
            classify_url("https://replicate.com"),
            URLClassification.GENERIC_PLATFORM_URL,
        )
        self.assertEqual(
            classify_url("https://huggingface.co"),
            URLClassification.GENERIC_PLATFORM_URL,
        )

        # REPOSITORY_URL
        self.assertEqual(
            classify_url("https://github.com/openai/whisper"),
            URLClassification.REPOSITORY_URL,
        )

        # ENTITY_SPECIFIC_URL
        self.assertEqual(
            classify_url("https://www.anthropic.com"),
            URLClassification.ENTITY_SPECIFIC_URL,
        )
        self.assertEqual(
            classify_url("https://cursor.com"),
            URLClassification.ENTITY_SPECIFIC_URL,
        )
        self.assertEqual(
            classify_url("https://arxiv.org/abs/2301.00001"),
            URLClassification.ENTITY_SPECIFIC_URL,
        )

        # UNKNOWN_URL
        self.assertEqual(classify_url(""), URLClassification.UNKNOWN_URL)
        self.assertEqual(classify_url(None), URLClassification.UNKNOWN_URL)

    def test_name_compatibility_logic(self):
        """Verify name compatibility guards prevent unrelated entities from matching."""
        # Unrelated entities must NEVER be compatible
        self.assertFalse(are_names_compatible("Cursor", "Mistral La Plateforme"))
        self.assertFalse(are_names_compatible("Windsurf", "Mistral La Plateforme"))
        self.assertFalse(are_names_compatible("GitHub Copilot", "Mistral La Plateforme"))
        self.assertFalse(are_names_compatible("OpenAI Moderation", "Whisper"))
        self.assertFalse(are_names_compatible("Flux", "Replicate"))
        self.assertFalse(are_names_compatible("Warp", "Mistral La Plateforme"))

        # Compatible entities must be accepted
        self.assertTrue(are_names_compatible("AssemblyAI", "AssemblyAI"))
        self.assertTrue(are_names_compatible("AssemblyAI, Inc.", "AssemblyAI"))
        self.assertTrue(are_names_compatible("Anthropic PBC", "Anthropic"))
        self.assertTrue(are_names_compatible("OpenAI", "OpenAI API"))

    def test_name_normalization_and_legal_suffixes(self):
        """Test normalization removes punctuation, lowercases, and strips legal suffixes."""
        self.assertEqual(normalize_entity_name("OpenAI, Inc."), "openai")
        self.assertEqual(normalize_entity_name("Anthropic PBC LLC"), "anthropic pbc")
        self.assertEqual(normalize_entity_name("Cohere Technologies Corp."), "cohere")
        self.assertEqual(normalize_entity_name("Stability AI"), "stability ai")

    def test_root_domain_extraction(self):
        """Test domain extraction strips subdomains and excludes generic aggregators."""
        self.assertEqual(extract_root_domain("https://www.openai.com/research"), "openai.com")
        self.assertEqual(extract_root_domain("https://api.anthropic.com/v1"), "anthropic.com")
        self.assertEqual(extract_root_domain("https://careers.anthropic.com/roles"), "anthropic.com")
        self.assertIsNone(extract_root_domain("https://github.com/vllm-project/vllm"))
        self.assertIsNone(extract_root_domain("https://www.ycombinator.com/companies/stripe"))
        self.assertIsNone(extract_root_domain("https://replicate.com/docs"))

    # --- Legitimate Duplicate Merge Tests ---

    def test_exact_name_matching(self):
        """Test exact normalized name matching merges entities with confidence 0.95."""
        id1, name1, method1, conf1 = self.resolver.resolve_entity(
            entity_name="OpenAI, Inc.",
            entity_type="COMPANY",
            source_url="https://source1.com/item1",
        )
        id2, name2, method2, conf2 = self.resolver.resolve_entity(
            entity_name="OpenAI",
            entity_type="COMPANY",
            source_url="https://source2.com/item2",
        )
        self.assertEqual(id1, id2)
        self.assertEqual(name1, name2)
        self.assertEqual(method2, "EXACT_NORMALIZED_NAME")
        self.assertEqual(conf2, 0.95)

    def test_domain_matching_legitimate(self):
        """Test domain matching merges entities with compatible names and matching root domains."""
        id1, name1, method1, conf1 = self.resolver.resolve_entity(
            entity_name="Anthropic",
            entity_type="COMPANY",
            source_url="https://ycombinator.com/companies/anthropic",
            website="https://www.anthropic.com",
        )
        id2, name2, method2, conf2 = self.resolver.resolve_entity(
            entity_name="Anthropic PBC",
            entity_type="COMPANY",
            source_url="https://jobicy.com/anthropic-jobs",
            website="https://careers.anthropic.com/roles",
        )
        self.assertEqual(id1, id2)
        self.assertEqual(name2, "Anthropic")
        self.assertEqual(method2, "EXACT_DOMAIN")
        self.assertEqual(conf2, 0.98)

    def test_legitimate_assemblyai_merge(self):
        """Test AssemblyAI startup and product company merge legitimately via domain and name."""
        id1, name1, _, _ = self.resolver.resolve_entity(
            entity_name="AssemblyAI",
            entity_type="COMPANY",
            source_url="https://www.ycombinator.com/companies/assemblyai",
            website="https://www.assemblyai.com",
        )
        id2, name2, method2, conf2 = self.resolver.resolve_entity(
            entity_name="AssemblyAI",
            entity_type="COMPANY",
            source_url="https://assemblyai.com/docs",
            website="https://assemblyai.com",
        )
        self.assertEqual(id1, id2)
        self.assertEqual(method2, "EXACT_DOMAIN")
        self.assertEqual(conf2, 0.98)

    def test_fuzzy_name_matching(self):
        """Test fuzzy name matching merges high-similarity variations above threshold."""
        id1, name1, _, _ = self.resolver.resolve_entity(
            entity_name="Midjourney, Inc.",
            entity_type="COMPANY",
            source_url="https://source1.com",
            website="https://midjourney.com",
        )
        id2, name2, method2, conf2 = self.resolver.resolve_entity(
            entity_name="Midjourny",
            entity_type="COMPANY",
            source_url="https://source2.com",
            website=None,
        )
        self.assertEqual(id1, id2)
        self.assertEqual(method2, "FUZZY_NAME")
        self.assertGreaterEqual(conf2, 0.80)
        self.assertLessEqual(conf2, 0.90)

    # --- Regression Tests for Audit False Positives ---

    def test_regression_cursor_vs_mistral_not_merged(self):
        """REGRESSION: Cursor must NOT merge into Mistral La Plateforme via shared GitHub directory URL."""
        id1, name1, _, _ = self.resolver.resolve_entity(
            entity_name="Mistral La Plateforme",
            entity_type="PRODUCT",
            source_url="https://github.com/ShaikhWarsi/free-ai-tools",
            website="https://github.com/ShaikhWarsi/free-ai-tools",
        )
        id2, name2, method2, _ = self.resolver.resolve_entity(
            entity_name="Cursor",
            entity_type="PRODUCT",
            source_url="https://github.com/ShaikhWarsi/free-ai-tools",
            website="https://github.com/ShaikhWarsi/free-ai-tools",
        )
        self.assertNotEqual(id1, id2)
        self.assertEqual(method2, "NEW_CANONICAL_SEED")

    def test_regression_windsurf_vs_mistral_not_merged(self):
        """REGRESSION: Windsurf must NOT merge into Mistral La Plateforme."""
        id1, _, _, _ = self.resolver.resolve_entity(
            entity_name="Mistral La Plateforme",
            entity_type="PRODUCT",
            source_url="https://github.com/ShaikhWarsi/free-ai-tools",
            website="https://github.com/ShaikhWarsi/free-ai-tools",
        )
        id2, _, method2, _ = self.resolver.resolve_entity(
            entity_name="Windsurf",
            entity_type="PRODUCT",
            source_url="https://github.com/ShaikhWarsi/free-ai-tools",
            website="https://github.com/ShaikhWarsi/free-ai-tools",
        )
        self.assertNotEqual(id1, id2)
        self.assertEqual(method2, "NEW_CANONICAL_SEED")

    def test_regression_github_copilot_vs_mistral_not_merged(self):
        """REGRESSION: GitHub Copilot must NOT merge into Mistral La Plateforme."""
        id1, _, _, _ = self.resolver.resolve_entity(
            entity_name="Mistral La Plateforme",
            entity_type="PRODUCT",
            source_url="https://github.com/ShaikhWarsi/free-ai-tools",
            website="https://github.com/ShaikhWarsi/free-ai-tools",
        )
        id2, _, method2, _ = self.resolver.resolve_entity(
            entity_name="GitHub Copilot",
            entity_type="PRODUCT",
            source_url="https://github.com/ShaikhWarsi/free-ai-tools",
            website="https://github.com/ShaikhWarsi/free-ai-tools",
        )
        self.assertNotEqual(id1, id2)
        self.assertEqual(method2, "NEW_CANONICAL_SEED")

    def test_regression_openai_moderation_vs_whisper_not_merged(self):
        """REGRESSION: OpenAI Moderation must NOT merge with Whisper via platform.openai.com portal URL."""
        id1, name1, _, _ = self.resolver.resolve_entity(
            entity_name="Whisper (OpenAI)",
            entity_type="PRODUCT",
            source_url="https://developers.openai.com/api/docs/guides/speech-to-text",
            website="https://platform.openai.com",
        )
        id2, name2, method2, _ = self.resolver.resolve_entity(
            entity_name="OpenAI Moderation",
            entity_type="PRODUCT",
            source_url="https://developers.openai.com/api/docs/guides/moderation",
            website="https://platform.openai.com",
        )
        self.assertNotEqual(id1, id2)
        self.assertEqual(method2, "NEW_CANONICAL_SEED")

    def test_regression_flux_vs_replicate_not_merged(self):
        """REGRESSION: Flux must NOT merge into Replicate hosting platform."""
        id1, _, _, _ = self.resolver.resolve_entity(
            entity_name="Replicate",
            entity_type="PRODUCT",
            source_url="https://replicate.com/docs",
            website="https://replicate.com/docs",
        )
        id2, _, method2, _ = self.resolver.resolve_entity(
            entity_name="Flux (via Replicate)",
            entity_type="PRODUCT",
            source_url="https://replicate.com/docs",
            website="https://replicate.com/docs",
        )
        self.assertNotEqual(id1, id2)
        self.assertEqual(method2, "NEW_CANONICAL_SEED")

    def test_regression_shared_directory_urls_no_cross_merge(self):
        """REGRESSION: Multiple tools on the same directory list must all remain separate entities."""
        tools = ["Qoder", "PrixAI", "Bito", "Sourcery", "Gemini CLI", "Rovo Dev CLI", "Warp", "Amazon Q Developer"]
        ids = set()
        for tool in tools:
            cid, _, method, _ = self.resolver.resolve_entity(
                entity_name=tool,
                entity_type="PRODUCT",
                source_url="https://github.com/ShaikhWarsi/free-ai-tools",
                website="https://github.com/ShaikhWarsi/free-ai-tools",
            )
            ids.add(cid)
            self.assertEqual(method, "NEW_CANONICAL_SEED")
        # Every tool must produce its own distinct canonical entity
        self.assertEqual(len(ids), len(tools))

    # --- Other Safeguard & Idempotence Tests ---

    def test_different_companies_similar_names_different_domains(self):
        """Test companies with similar names but conflicting domains are NOT merged."""
        id1, name1, _, _ = self.resolver.resolve_entity(
            entity_name="Scale AI",
            entity_type="COMPANY",
            source_url="https://source1.com",
            website="https://scale.com",
        )
        id2, name2, method2, _ = self.resolver.resolve_entity(
            entity_name="Scale Network",
            entity_type="COMPANY",
            source_url="https://source2.com",
            website="https://scale.network",
        )
        self.assertNotEqual(id1, id2)
        self.assertEqual(method2, "NEW_CANONICAL_SEED")

    def test_entities_with_missing_websites(self):
        """Test entities with missing websites resolve via name when matched, or remain separate."""
        id1, name1, _, _ = self.resolver.resolve_entity(
            entity_name="Perplexity AI",
            entity_type="COMPANY",
            source_url="https://source1.com",
            website=None,
        )
        id2, name2, method2, conf2 = self.resolver.resolve_entity(
            entity_name="Perplexity AI",
            entity_type="COMPANY",
            source_url="https://source2.com",
            website=None,
        )
        self.assertEqual(id1, id2)
        self.assertEqual(method2, "EXACT_NORMALIZED_NAME")

        id3, name3, method3, _ = self.resolver.resolve_entity(
            entity_name="Harvey Legal AI",
            entity_type="COMPANY",
            source_url="https://source3.com",
            website=None,
        )
        self.assertNotEqual(id1, id3)
        self.assertEqual(method3, "NEW_CANONICAL_SEED")

    def test_ambiguous_matches_remain_unresolved(self):
        """Test ambiguous entities below threshold remain unresolved as separate entities."""
        id1, name1, _, _ = self.resolver.resolve_entity(
            entity_name="Meta Platforms",
            entity_type="COMPANY",
            source_url="https://source1.com",
            website="https://meta.com",
        )
        id2, name2, method2, _ = self.resolver.resolve_entity(
            entity_name="MetaMorph AI",
            entity_type="COMPANY",
            source_url="https://source2.com",
            website="https://metamorph.ai",
        )
        self.assertNotEqual(id1, id2)
        self.assertEqual(method2, "NEW_CANONICAL_SEED")

    def test_already_resolved_entity_idempotence(self):
        """Test that passing an already resolved entity returns the canonical ID with ALREADY_RESOLVED."""
        id1, name1, _, _ = self.resolver.resolve_entity(
            entity_name="Cohere",
            entity_type="COMPANY",
            source_url="https://cohere.com",
            website="https://cohere.com",
        )
        id2, name2, method2, conf2 = self.resolver.resolve_entity(
            entity_name="Cohere",
            entity_type="COMPANY",
            source_url="https://cohere.com",
            already_canonical_id=id1,
        )
        self.assertEqual(id1, id2)
        self.assertEqual(name1, name2)
        self.assertEqual(method2, "ALREADY_RESOLVED")
        self.assertEqual(conf2, 1.0)

    def test_confidence_score_semantics_new_seed(self):
        """Test that NEW_CANONICAL_SEED assigns confidence score 0.0 (unmatched baseline seed)."""
        _, _, method, conf = self.resolver.resolve_entity(
            entity_name="NewUniqueCompany",
            entity_type="COMPANY",
            source_url="https://unique.ai",
            website="https://unique.ai",
        )
        self.assertEqual(method, "NEW_CANONICAL_SEED")
        self.assertEqual(conf, 0.0)

    def test_source_records_preservation(self):
        """Test that original input records are preserved without mutation or deletion."""
        original_startups = [
            {"company_name": "Groq", "website": "https://groq.com", "source_url": "https://yc.com/groq"}
        ]
        original_copy = [dict(x) for x in original_startups]

        resolver, datasets = resolve_all_intelligence_entities(
            startups=original_startups,
            products=[],
            papers=[],
            export_csv=False,
        )
        self.assertEqual(original_startups, original_copy)
        self.assertIn("canonical_entity_id", datasets["startups"][0])
        self.assertIn("canonical_entity_name", datasets["startups"][0])

    def test_mapping_log_schema(self):
        """Test that entity mapping log contains all 7 required columns."""
        self.resolver.resolve_entity(
            entity_name="Mistral",
            entity_type="COMPANY",
            source_url="https://mistral.ai",
            website="https://mistral.ai",
        )
        df = self.resolver.get_mapping_logs_df()
        expected_columns = [
            "original_entity_name",
            "canonical_entity_name",
            "canonical_entity_id",
            "source_url",
            "matching_method",
            "confidence_score",
            "resolution_timestamp",
        ]
        self.assertEqual(list(df.columns), expected_columns)
        self.assertEqual(len(df), 1)


if __name__ == "__main__":
    unittest.main()
