#!/usr/bin/env python3
"""Live OfferToday coverage audit.

This script measures how much of OfferToday's IT surface the crawler can reach
by replaying the same planner and browser transport that the crawler uses.

It prints per-family counts for:
  - pages fetched
  - raw listing rows returned
  - unique job IDs discovered
  - duplicate job IDs suppressed

The script exits non-zero if the measured unique job ID total does not reach
the requested threshold.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("offertoday-audit")

BACKEND = str(Path(__file__).resolve().parents[1])
SCRAPY_PROJECT = str(Path(__file__).resolve().parents[1] / "scrapy_project")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
if SCRAPY_PROJECT not in sys.path:
    sys.path.insert(0, SCRAPY_PROJECT)

from app.sources.offertoday.constants import (
    OFFERTODAY_BASE_URL,
    OFFERTODAY_COMMON_HEADERS,
    OFFERTODAY_LISTING_BROWSE_URL,
    OFFERTODAY_LISTING_SEARCH_URL,
    build_offertoday_listing_payload,
)
from app.sources.offertoday.parsers import parse_offertoday_listing_response  # noqa: E402
from app.sources.offertoday.search_space import build_offertoday_listing_queries, normalize_offertoday_keywords  # noqa: E402
from job_scraper_spiders.downloaders.offertoday_transport import PlaywrightPageTransport  # noqa: E402

OFFERTODAY_SEARCH_URL = f"{OFFERTODAY_BASE_URL}/hk/search"

MAX_PAGES_GLOBAL = 9999
DEFAULT_MAX_PAGES = 100
DEFAULT_WARMUP_DELAY_SECONDS = 2.0

_COMMON_HEADERS = OFFERTODAY_COMMON_HEADERS


@dataclass
class CoverageFamilyStats:
    search_family: str
    pages_fetched: int = 0
    listing_rows: int = 0
    sample_unique_job_ids: int = 0
    duplicate_job_ids: int = 0
    failed_pages: int = 0
    reported_total: int = 0


@dataclass
class CoverageConditionStats:
    family: str
    category_id: int | None
    keyword: str
    reported_total: int = 0


@dataclass
class CoverageAuditResult:
    target_unique_job_ids: int
    planned_tasks: int
    processed_tasks: int = 0
    global_reported_total: int = 0
    global_sample_unique_job_ids: int = 0
    stopped_early: bool = False
    last_family_with_new_ids: str | None = None
    family_order: list[str] = field(default_factory=list)
    families: dict[str, CoverageFamilyStats] = field(default_factory=dict)
    conditions: list[CoverageConditionStats] = field(default_factory=list)


def _parse_category_ids(raw_category_ids: str) -> list[int]:
    category_ids: list[int] = []
    for value in raw_category_ids.split(","):
        cleaned = value.strip()
        if cleaned.isdigit():
            category_ids.append(int(cleaned))
    return category_ids


def _get_family_stats(result: CoverageAuditResult, family: str) -> CoverageFamilyStats:
    stats = result.families.get(family)
    if stats is None:
        stats = CoverageFamilyStats(search_family=family)
        result.families[family] = stats
        result.family_order.append(family)
    return stats


def render_coverage_audit_report(result: CoverageAuditResult) -> str:
    """Render a stable, human-readable audit report."""
    lines = [
        "OfferToday coverage audit",
        f"Planned tasks: {result.planned_tasks}",
        f"Processed tasks: {result.processed_tasks}",
        f"Target unique job IDs: {result.target_unique_job_ids}",
        f"Global reported total: {result.global_reported_total}",
        f"Global sample unique rows: {result.global_sample_unique_job_ids}",
        f"Target reached: {'yes' if result.global_sample_unique_job_ids >= result.target_unique_job_ids else 'no'}",
        f"Shortfall: {max(result.target_unique_job_ids - result.global_sample_unique_job_ids, 0)}",
    ]

    if result.last_family_with_new_ids:
        lines.append(f"Last family with new IDs: {result.last_family_with_new_ids}")
    if result.stopped_early:
        lines.append("Stopped early: yes")

    lines.append(
        "Planned families: "
        + (", ".join(result.family_order) if result.family_order else "[none]")
    )
    lines.append("")
    lines.append(
        f"{'Family':<20} {'Pages':>5} {'Rows':>6} {'Sample':>7} {'Total':>7} {'Dups':>7} {'Fails':>6}"
    )
    lines.append("-" * 70)

    for family in result.family_order:
        stats = result.families[family]
        lines.append(
            f"{family:<20} {stats.pages_fetched:>5} {stats.listing_rows:>6} "
            f"{stats.sample_unique_job_ids:>7} {stats.reported_total:>7} "
            f"{stats.duplicate_job_ids:>7} {stats.failed_pages:>6}"
        )

    if not result.family_order:
        lines.append("(no families planned)")

    if result.conditions:
        lines.append("")
        lines.append(
            f"{'Family':<20} {'Cat ID':>7} {'Keyword':<25} {'API Total':>10}"
        )
        lines.append("-" * 70)
        for cond in result.conditions:
            cat = str(cond.category_id) if cond.category_id is not None else "-"
            lines.append(
                f"{cond.family:<20} {cat:>7} {cond.keyword:<25} {cond.reported_total:>10}"
            )

    return "\n".join(lines)


async def run_offertoday_coverage_audit(
    *,
    category_ids: list[int],
    keywords: str,
    max_pages_per_query: int,
    target_unique_job_ids: int,
    listing_url: str | None = None,
) -> CoverageAuditResult:
    """Fetch OfferToday listing pages and count unique IDs by search family.

    ``listing_url`` selects the API endpoint:
    - None / OFFERTODAY_LISTING_SEARCH_URL (default): recommendation-filtered search
    - OFFERTODAY_LISTING_BROWSE_URL: plain category browse (use to test hypothesis B)
    """
    if max_pages_per_query < 1:
        raise ValueError("max_pages_per_query must be >= 1")
    if max_pages_per_query > MAX_PAGES_GLOBAL:
        raise ValueError(f"max_pages_per_query must be <= {MAX_PAGES_GLOBAL}")
    if target_unique_job_ids < 1:
        raise ValueError("target_unique_job_ids must be >= 1")

    normalized_keywords = normalize_offertoday_keywords(keywords)
    listing_tasks = build_offertoday_listing_queries(
        category_ids,
        keywords=normalized_keywords or None,
        max_pages_per_query=max_pages_per_query,
    )
    result = CoverageAuditResult(
        target_unique_job_ids=target_unique_job_ids,
        planned_tasks=len(listing_tasks),
    )
    global_seen_ids: set[str] = set()
    seen_reported_conditions: set[tuple[str, Any, str]] = set()
    exhausted_conditions: set[tuple[Any, str]] = set()  # (category_id, keyword) → empty page seen

    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = None
        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="zh-HK",
            )
            page = await context.new_page()

            await page.goto(OFFERTODAY_SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(DEFAULT_WARMUP_DELAY_SECONDS)

            transport = PlaywrightPageTransport(page, listing_url=listing_url or OFFERTODAY_LISTING_SEARCH_URL)

            for task in listing_tasks:
                family = str(task.get("search_family") or "").strip() or "category_search"
                stats = _get_family_stats(result, family)
                category_id = task.get("category_id")
                keyword = str(task.get("keyword") or "")
                page_number = int(task.get("page") or 1)
                condition_key = (family, category_id, keyword)

                # Skip remaining pages for conditions that already returned empty results.
                exhaustion_key = (category_id, keyword)
                if exhaustion_key in exhausted_conditions:
                    logger.debug(
                        "Skipping exhausted condition family=%s cat=%s keyword=%s page=%s",
                        family, category_id, keyword, page_number,
                    )
                    continue

                result.processed_tasks += 1
                stats.pages_fetched += 1

                try:
                    task_listing_url = (
                        OFFERTODAY_LISTING_BROWSE_URL
                        if task.get("endpoint") == "browse"
                        else listing_url or OFFERTODAY_LISTING_SEARCH_URL
                    )
                    response = await transport.fetch_listing(
                        build_offertoday_listing_payload(
                            category_id=category_id,
                            keyword=keyword,
                            page=page_number,
                        ),
                        listing_url=task_listing_url,
                    )
                except Exception as exc:  # pragma: no cover - live transport failure path
                    stats.failed_pages += 1
                    logger.warning(
                        "OfferToday listing fetch failed for family=%s category=%s keyword=%s page=%s: %s",
                        family,
                        category_id,
                        keyword,
                        page_number,
                        exc,
                    )
                    continue

                if not response or response.get("code") != 0:
                    stats.failed_pages += 1
                    logger.warning(
                        "OfferToday listing returned non-success payload for family=%s category=%s keyword=%s page=%s: code=%s",
                        family,
                        category_id,
                        keyword,
                        page_number,
                        response.get("code") if isinstance(response, dict) else None,
                    )
                    continue

                if condition_key not in seen_reported_conditions:
                    condition_total = int(response.get("data", {}).get("total") or 0)
                    stats.reported_total += condition_total
                    result.global_reported_total += condition_total
                    seen_reported_conditions.add(condition_key)
                    result.conditions.append(
                        CoverageConditionStats(
                            family=family,
                            category_id=category_id,
                            keyword=keyword,
                            reported_total=condition_total,
                        )
                    )

                parsed_jobs = parse_offertoday_listing_response(response)
                stats.listing_rows += len(parsed_jobs)

                if not parsed_jobs:
                    # Mark this (category_id, keyword) pair exhausted so subsequent
                    # pages for the same condition are skipped without fetching.
                    exhausted_conditions.add((category_id, keyword))
                    logger.debug(
                        "Condition exhausted family=%s cat=%s keyword=%s page=%s",
                        family, category_id, keyword, page_number,
                    )
                    continue

                for job in parsed_jobs:
                    job_id = str(job.get("encrypted_job_id") or "").strip()
                    if not job_id:
                        continue
                    if job_id in global_seen_ids:
                        stats.duplicate_job_ids += 1
                        continue

                    global_seen_ids.add(job_id)
                    stats.sample_unique_job_ids += 1
                    result.global_sample_unique_job_ids += 1
                    result.last_family_with_new_ids = family

                if result.global_sample_unique_job_ids >= target_unique_job_ids:
                    result.stopped_early = True
                    break
        finally:
            if context is not None:
                await context.close()
            await browser.close()

    return result


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live OfferToday coverage audit")
    parser.add_argument(
        "--category-ids",
        type=str,
        nargs="?",
        const="",
        default="",
        help="Comma-separated OfferToday category IDs",
    )
    parser.add_argument(
        "--keywords",
        type=str,
        nargs="?",
        const="",
        default="",
        help="Comma-separated keyword probes",
    )
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="Max pages per query condition")
    parser.add_argument(
        "--use-browse-endpoint",
        action="store_true",
        default=False,
        help=(
            "Use the plain category-browse endpoint (/recommend/list) instead of the default "
            "recommendation-search endpoint (/recommend/search/list). "
            "Use this to test whether the search endpoint is under-counting results."
        ),
    )
    parser.add_argument(
        "--target-unique-job-ids",
        type=int,
        required=True,
        help="Unique job ID threshold required for a passing audit",
    )
    return parser


async def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        listing_url = OFFERTODAY_LISTING_BROWSE_URL if args.use_browse_endpoint else OFFERTODAY_LISTING_SEARCH_URL
        result = await run_offertoday_coverage_audit(
            category_ids=_parse_category_ids(args.category_ids),
            keywords=args.keywords,
            max_pages_per_query=int(args.max_pages),
            target_unique_job_ids=int(args.target_unique_job_ids),
            listing_url=listing_url,
        )
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    print(render_coverage_audit_report(result))
    return 0 if result.global_sample_unique_job_ids >= result.target_unique_job_ids else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
