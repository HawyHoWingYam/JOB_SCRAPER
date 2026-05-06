from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.scraper.ctgoodjobs.detail_scraper import parse_detail_page as existing_parse_detail_page
from app.scraper.ctgoodjobs.list_scraper import parse_category_page as existing_parse_category_page

from app.sources.ctgoodjobs import parsers


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ctgoodjobs"


def test_parse_ctgoodjobs_category_page_matches_existing_parser_output():
    html = (FIXTURES / "category_page.html").read_text(encoding="utf-8")

    expected = existing_parse_category_page(
        html,
        category_slug="data-jobs",
        source_classification_id="ctgoodjobs:021",
        source_classification_name="Data Jobs",
        page=2,
        url="https://jobs.ctgoodjobs.hk/jobs/data-jobs?page=2",
    )
    actual = parsers.parse_category_page(
        html,
        category_slug="data-jobs",
        source_classification_id="ctgoodjobs:021",
        source_classification_name="Data Jobs",
        page=2,
        url="https://jobs.ctgoodjobs.hk/jobs/data-jobs?page=2",
    )

    assert actual == expected


def test_parse_ctgoodjobs_detail_page_matches_existing_parser_output():
    html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")

    expected = existing_parse_detail_page(
        html,
        source_classification_id="ctgoodjobs:021",
        source_classification_name="Data Jobs",
        source_classification_slug="data-jobs",
        url="https://jobs.ctgoodjobs.hk/job/10090657",
    )
    actual = parsers.parse_detail_page(
        html,
        source_classification_id="ctgoodjobs:021",
        source_classification_name="Data Jobs",
        source_classification_slug="data-jobs",
        url="https://jobs.ctgoodjobs.hk/job/10090657",
    )

    assert actual == expected
