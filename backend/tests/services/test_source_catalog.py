from __future__ import annotations

from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.source_catalog import (
    build_source_catalog,
    list_supported_source_sites,
    resolve_default_max_pages,
)


def test_source_catalog_exposes_supported_sources_and_defaults():
    catalog = build_source_catalog()

    assert list_supported_source_sites() == ("jobsdb", "ctgoodjobs", "offertoday")
    assert catalog["jobsdb"]["label"] == "JobsDB"
    assert catalog["jobsdb"]["default_crawl_mode"] == "headed"
    assert catalog["jobsdb"]["default_max_pages"] == 3
    assert catalog["ctgoodjobs"]["supported_crawl_modes"] == ["headed"]
    assert catalog["offertoday"]["default_max_pages"] == 50


def test_resolve_default_max_pages_is_source_aware():
    assert resolve_default_max_pages("jobsdb") == 3
    assert resolve_default_max_pages("ctgoodjobs") == 3
    assert resolve_default_max_pages("offertoday") == 50


def test_manual_dispatch_uses_source_default_max_pages_when_max_pages_is_missing():
    payload = CrawlJobDispatchService().build_manual_request_payload(
        source_site="offertoday",
        crawl_phase="listing",
        crawl_mode=None,
        category_ids=[],
        keywords=None,
        max_pages=None,
    )

    assert payload["max_pages"] == 50


def test_manual_dispatch_preserves_explicit_max_pages():
    payload = CrawlJobDispatchService().build_manual_request_payload(
        source_site="offertoday",
        crawl_phase="listing",
        crawl_mode=None,
        category_ids=[],
        keywords=None,
        max_pages=12,
    )

    assert payload["max_pages"] == 12
