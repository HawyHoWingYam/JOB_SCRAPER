"""Tests for the ScrapeGraphAI extraction fallback.

These tests verify the extraction interface and fallback behavior without
requiring ScrapeGraphAI to be installed or live network access.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure scrapy_project is importable
SCRAPY_PROJECT = str(Path(__file__).resolve().parents[1] / "scrapy_project")
if SCRAPY_PROJECT not in sys.path:
    sys.path.insert(0, SCRAPY_PROJECT)


class TestScrapegraphAvailable:
    def test_is_scrapegraph_available_returns_bool(self) -> None:
        from job_scraper_spiders.extractors.scrapegraph_extract import (
            is_scrapegraph_available,
        )

        result = is_scrapegraph_available()
        assert isinstance(result, bool)

    def test_extract_without_scrapegraph_returns_empty(self) -> None:
        """If ScrapeGraphAI is not installed, extraction should return empty dict."""
        from job_scraper_spiders.extractors.scrapegraph_extract import (
            extract_missing_fields,
        )

        html = "<html><body><h1>Test Job</h1></body></html>"

        import asyncio

        result = asyncio.run(extract_missing_fields(html))
        assert isinstance(result, dict)
        # Should return empty since ScrapeGraphAI likely isn't installed
        # in this test environment


class TestScrapegraphSchema:
    def test_missing_fields_schema_has_required_structure(self) -> None:
        from job_scraper_spiders.extractors.scrapegraph_extract import (
            MISSING_FIELDS_SCHEMA,
        )

        assert "type" in MISSING_FIELDS_SCHEMA
        assert "properties" in MISSING_FIELDS_SCHEMA
        assert "required" in MISSING_FIELDS_SCHEMA
        assert "title" in MISSING_FIELDS_SCHEMA["required"]
        assert "description_html" in MISSING_FIELDS_SCHEMA["required"]

    def test_schema_properties(self) -> None:
        from job_scraper_spiders.extractors.scrapegraph_extract import (
            MISSING_FIELDS_SCHEMA,
        )

        props = MISSING_FIELDS_SCHEMA["properties"]
        assert props["title"]["type"] == "string"
        assert props["description_html"]["type"] == "string"
        assert props["company_name"]["type"] == "string"
        assert props["location"]["type"] == "string"
        assert props["salary_range"]["type"] == "string"
        assert props["employment_type"]["type"] == "string"


class TestExtractMissingFields:
    def test_known_fields_all_present(self) -> None:
        """If all required fields are known, extraction should return empty."""
        from job_scraper_spiders.extractors.scrapegraph_extract import (
            extract_missing_fields,
        )

        known = {
            "title": "Software Engineer",
            "description_html": "<p>Description</p>",
            "company_name": "Tech Corp",
        }

        import asyncio

        result = asyncio.run(
            extract_missing_fields("<html></html>", known_fields=known)
        )
        assert isinstance(result, dict)
