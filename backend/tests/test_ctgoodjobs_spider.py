from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.sources.ctgoodjobs import parsers


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ctgoodjobs"


def test_ctgoodjobs_spider_builds_canonical_item_from_parsed_detail():
    from crawler.job_crawler.spiders.ctgoodjobs_spider import build_canonical_job

    html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")
    parsed = parsers.parse_detail_page(
        html,
        source_classification_id="ctgoodjobs:021",
        source_classification_name="Data Jobs",
        source_classification_slug="data-jobs",
        url="https://jobs.ctgoodjobs.hk/job/10090657",
    )
    item = build_canonical_job(parsed)

    assert item.source_site == "ctgoodjobs"
    assert item.source_job_id == "10090657"
    assert item.source_url == "https://jobs.ctgoodjobs.hk/job/10090657"
    assert item.title == "Lead Data Analyst | CTgoodjobs"
