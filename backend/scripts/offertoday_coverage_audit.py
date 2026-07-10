#!/usr/bin/env python3
"""Live OfferToday coverage audit.

This compatibility wrapper measures OfferToday coverage through the production
listing runner and authenticated browser runtime.

It prints per-family counts for:
  - pages fetched
  - raw listing rows returned
  - unique job IDs discovered
  - duplicate job IDs suppressed

The requested unique-ID threshold is diagnostic only. Completeness is decided
by the shared runner's stop contract.
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
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime  # noqa: E402
from app.sources.offertoday.constants import (  # noqa: E402
    OFFERTODAY_LISTING_BROWSE_URL,
    OFFERTODAY_LISTING_SEARCH_URL,
)
from app.sources.offertoday.listing_runner import (  # noqa: E402
    ListingRetryPolicy,
    ListingStopPolicy,
    OfferTodayListingRunner,
)
from app.sources.offertoday.search_space import (  # noqa: E402
    build_offertoday_listing_conditions,
    normalize_offertoday_keywords,
)
from scripts.offertoday_standalone_crawl import (  # noqa: E402
    MemoryListingObservationSink,
    NoopListingStagingSink,
)

MAX_PAGES_GLOBAL = 9999
DEFAULT_MAX_PAGES = 100


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
    listing_result: Any
    processed_tasks: int = 0
    global_reported_total: int = 0
    global_sample_unique_job_ids: int = 0
    stopped_early: bool = False
    last_family_with_new_ids: str | None = None
    family_order: list[str] = field(default_factory=list)
    families: dict[str, CoverageFamilyStats] = field(default_factory=dict)
    conditions: list[CoverageConditionStats] = field(default_factory=list)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.listing_result, name)


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
        f"Threshold reached: {'yes' if result.global_sample_unique_job_ids >= result.target_unique_job_ids else 'no'}",
        f"Shortfall: {max(result.target_unique_job_ids - result.global_sample_unique_job_ids, 0)}",
        f"Runner complete: {'yes' if result.is_complete else 'no'}",
        f"Runner stop reason: {result.stop_reason}",
        (
            "Deprecated for future live research: use offertoday_research.py "
            "after Plan 2 census commands are available."
        ),
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


def _summarize_listing_result(
    listing_result,
    *,
    target_unique_job_ids: int,
    planned_tasks: int,
    planned_families: list[str],
) -> CoverageAuditResult:
    result = CoverageAuditResult(
        target_unique_job_ids=target_unique_job_ids,
        planned_tasks=planned_tasks,
        listing_result=listing_result,
        processed_tasks=len(listing_result.observations),
        global_sample_unique_job_ids=len(listing_result.ordered_job_ids),
        stopped_early=False,
    )
    for family in planned_families:
        _get_family_stats(result, family)

    globally_seen_ids: set[str] = set()
    reported_condition_ids: set[str] = set()
    for observation in listing_result.observations:
        stats = _get_family_stats(result, observation.search_family)
        stats.pages_fetched += 1
        stats.listing_rows += int(observation.row_count)
        if observation.classification not in {"success", "contract_anomaly"}:
            stats.failed_pages += 1

        if (
            observation.condition_id not in reported_condition_ids
            and observation.reported_total is not None
        ):
            reported_total = int(observation.reported_total)
            reported_condition_ids.add(observation.condition_id)
            stats.reported_total += reported_total
            result.global_reported_total += reported_total
            result.conditions.append(
                CoverageConditionStats(
                    family=observation.search_family,
                    category_id=observation.category_id,
                    keyword=observation.keyword,
                    reported_total=reported_total,
                )
            )

        for row in observation.rows:
            job_id = str(row.job_id or "").strip()
            if not job_id:
                continue
            if job_id in globally_seen_ids:
                stats.duplicate_job_ids += 1
                continue
            globally_seen_ids.add(job_id)
            stats.sample_unique_job_ids += 1
            result.last_family_with_new_ids = observation.search_family
    return result


async def run_offertoday_coverage_audit(
    *,
    category_ids: list[int],
    keywords: str,
    max_pages_per_query: int,
    target_unique_job_ids: int,
    listing_url: str | None = None,
    browser_runtime=None,
    listing_runner=None,
) -> CoverageAuditResult:
    """Run the shared listing contract and summarize its saved observations."""
    if max_pages_per_query < 1:
        raise ValueError("max_pages_per_query must be >= 1")
    if max_pages_per_query > MAX_PAGES_GLOBAL:
        raise ValueError(f"max_pages_per_query must be <= {MAX_PAGES_GLOBAL}")
    if target_unique_job_ids < 1:
        raise ValueError("target_unique_job_ids must be >= 1")

    if listing_url in {None, OFFERTODAY_LISTING_SEARCH_URL}:
        endpoint = "search"
    elif listing_url == OFFERTODAY_LISTING_BROWSE_URL:
        endpoint = "browse"
    else:
        raise ValueError(f"Unsupported OfferToday listing URL: {listing_url!r}")

    conditions = build_offertoday_listing_conditions(
        category_ids,
        keywords=normalize_offertoday_keywords(keywords) or None,
        default_to_it=True,
        endpoint=endpoint,
    )
    observation_sink = MemoryListingObservationSink()
    staging_sink = NoopListingStagingSink()

    async def execute(active_runtime):
        await active_runtime.require_healthy_session()
        runner = listing_runner
        if runner is None:
            runner = OfferTodayListingRunner(active_runtime)
        elif isinstance(runner, type):
            runner = runner(active_runtime)
        return await runner.run(
            conditions=conditions,
            stop_policy=ListingStopPolicy(
                max_pages_per_condition=max_pages_per_query,
                unique_job_cap=None,
                require_empty_confirmation=True,
            ),
            retry_policy=ListingRetryPolicy(
                max_attempts_per_page=3,
                retry_delays_seconds=(1.0, 2.0),
                page_delay_seconds=1.5,
            ),
            observation_sink=observation_sink,
            staging_sink=staging_sink,
            session_mode="headless",
        )

    if browser_runtime is None:
        async with OfferTodayBrowserRuntime(headed=False) as active_runtime:
            listing_result = await execute(active_runtime)
    else:
        listing_result = await execute(browser_runtime)

    planned_families = list(
        dict.fromkeys(condition.search_family for condition in conditions)
    )
    return _summarize_listing_result(
        listing_result,
        target_unique_job_ids=target_unique_job_ids,
        planned_tasks=len(conditions) * max_pages_per_query,
        planned_families=planned_families,
    )


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
        help="Diagnostic unique job ID threshold (does not stop the crawl)",
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
    return 0 if result.is_complete else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
