from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.sources.jobsdb import parsers


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jobsdb"


def test_jobsdb_spider_builds_canonical_item_from_parsed_detail():
    from crawler.job_crawler.spiders.jobsdb_spider import build_canonical_job

    html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")
    parsed = parsers.parse_detail_page(html, job_id="123456")
    item = build_canonical_job(parsed, source_url="https://hk.jobsdb.com/job/123456")

    assert item.source_site == "jobsdb"
    assert item.source_job_id == "123456"
    assert item.source_url == "https://hk.jobsdb.com/job/123456"
    assert item.title == "Senior Data Analyst"
