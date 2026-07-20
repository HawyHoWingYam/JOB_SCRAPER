#!/usr/bin/env python3
"""Standalone CTGoodJobs crawl executor using source-specific browser/proxy runtime."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
import sys
import time
from typing import Any, Sequence
from uuid import uuid4

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("ctgoodjobs-crawl")

BACKEND = str(Path(__file__).resolve().parents[1])
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.repositories.company_repository import CompanyRepository  # noqa: E402
from app.crawl_control.runtime_authority import (  # noqa: E402
    load_legacy_worker_startup_input,
)
from app.repositories.job_repository import JobRepository  # noqa: E402
from app.scraper.ctgoodjobs.category_registry import CTGOODJOBS_BASE_URL  # noqa: E402
from app.scraper.ctgoodjobs.detail_scraper import parse_detail_page  # noqa: E402
from app.scraper.ctgoodjobs.list_scraper import category_page_url, parse_category_page  # noqa: E402
from app.scraper.ctgoodjobs.merge import merge_ctgoodjobs_job  # noqa: E402
from app.scraper.ctgoodjobs.page_state import CTGoodJobsTerminalUnavailableError  # noqa: E402
from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper  # noqa: E402
from app.scraper.log_events import build_scrape_log_event  # noqa: E402
from app.scraper.manual_action import (  # noqa: E402
    ManualActionRequiredError,
    build_session_recovery_manual_action,
)
from app.services.crawl_job_runtime import CrawlJobRuntime  # noqa: E402
from app.services.crawl_cancellation_token import (  # noqa: E402
    CrawlCancellationRequested,
    CrawlCancellationToken,
    resolve_cancellation_token,
)
from app.services.detail_pacing import build_detail_pacing_controller  # noqa: E402
from app.sources.contracts import build_ctgoodjobs_canonical_job  # noqa: E402
from app.source_catalog.runtime import load_published_scope_query_plan  # noqa: E402
from app.workers.run_ingest_worker import (  # noqa: E402
    IngestWorkerService,
    InvalidIngestPayloadError,
)

CTGOODJOBS_SOURCE_SITE = "ctgoodjobs"
DEFAULT_DETAIL_STATUSES = ["pending", "manual_action_required"]
CONTENT_ANOMALY_REASONS = frozenset({"missing_job_content", "missing_company_identity"})


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone CTGoodJobs crawler")
    parser.add_argument("--crawl-job-id", type=str, default="")
    parser.add_argument("--execution-generation", type=str, default="")
    parser.add_argument("--category-ids", type=str, default="")
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--detail-limit", type=int, default=100)
    parser.add_argument("--crawl-mode", choices=["headed"], default="headed")
    parser.add_argument("--crawl-phase", choices=["full", "listing", "detail"], default="full")
    parser.add_argument("--source-listing-crawl-job-id", type=str, default="")
    parser.add_argument("--detail-statuses", type=str, default="pending,manual_action_required")
    parser.add_argument("--skip-existing", action="store_true", default=False)
    parser.add_argument("--is-resume", action="store_true", default=False)
    parser.add_argument("--resume-strategy", type=str, default="fresh_profile")
    return parser


def _parse_category_ids(raw_value: str | Sequence[str]) -> list[str]:
    if isinstance(raw_value, (list, tuple)):
        return [str(value).strip() for value in raw_value if str(value).strip()]
    return [value.strip() for value in str(raw_value or "").split(",") if value.strip()]


def _parse_detail_statuses(raw_value: str | Sequence[str]) -> list[str]:
    if isinstance(raw_value, (list, tuple)):
        statuses = [str(value).strip() for value in raw_value if str(value).strip()]
    else:
        statuses = [value.strip() for value in str(raw_value or "").split(",") if value.strip()]
    return statuses or list(DEFAULT_DETAIL_STATUSES)


def _load_request_payload(crawl_job_id: str) -> tuple[dict[str, Any], str]:
    db = SessionLocal()
    try:
        startup = load_legacy_worker_startup_input(
            db,
            crawl_job_id=crawl_job_id,
            default_source_site=CTGOODJOBS_SOURCE_SITE,
        )
        return startup.request_payload, startup.source_site
    finally:
        db.close()


def _apply_request_payload_defaults(args, request_payload: dict[str, Any]) -> None:
    if not request_payload:
        return
    args.category_ids = _parse_category_ids(request_payload.get("category_ids") or [])
    args.max_pages = int(request_payload.get("max_pages") or args.max_pages)
    args.detail_limit = int(request_payload.get("detail_limit") or args.detail_limit)
    args.crawl_mode = str(request_payload.get("crawl_mode") or args.crawl_mode)
    requested_phase = str(request_payload.get("crawl_phase") or "").strip().lower()
    if requested_phase in {"listing", "detail"}:
        args.crawl_phase = requested_phase
    else:
        args.crawl_phase = "full"
    args.source_listing_crawl_job_id = str(
        request_payload.get("source_listing_crawl_job_id") or args.source_listing_crawl_job_id
    )
    args.detail_statuses = _parse_detail_statuses(request_payload.get("detail_statuses") or args.detail_statuses)
    args.skip_existing = bool(request_payload.get("skip_existing"))
    args.is_resume = bool(request_payload.get("is_resume"))
    args.resume_strategy = str(request_payload.get("resume_strategy") or args.resume_strategy)
    args.detail_pacing = request_payload.get("detail_pacing")


@dataclass(frozen=True)
class _PublishedCTGoodJobsCategory:
    source_classification_id: str
    ctgoodjobs_id: str
    name: str
    slug: str
    url: str


def _categories_by_id() -> dict[str, _PublishedCTGoodJobsCategory]:
    plan = load_published_scope_query_plan("ctgoodjobs", mode="all")
    categories: dict[str, _PublishedCTGoodJobsCategory] = {}
    for entry in plan.entries:
        classification_id = str(entry.node.classification_id or "").strip()
        if not classification_id:
            continue
        url_path = str(entry.target.payload.get("url_path") or "")
        categories[classification_id] = _PublishedCTGoodJobsCategory(
            source_classification_id=classification_id,
            ctgoodjobs_id=str(entry.target.payload.get("native_id") or ""),
            name=entry.node.native_label,
            slug=str(entry.node.source_metadata.get("slug") or ""),
            url=f"{CTGOODJOBS_BASE_URL}{url_path}",
        )
    return categories


def _resolve_category(category_lookup: dict[str, Any], category_id: str):
    category = category_lookup.get(str(category_id).strip())
    if category is None:
        raise RuntimeError(f"Unknown CTGoodJobs category: {category_id}")
    return category


def _build_browser_request_payload(args) -> dict[str, Any]:
    return {
        "crawl_job_id": args.crawl_job_id,
        "crawl_phase": args.crawl_phase,
        "crawl_mode": args.crawl_mode,
        "category_ids": list(args.category_ids),
        "max_pages": args.max_pages,
        "detail_limit": args.detail_limit,
        "detail_statuses": list(args.detail_statuses),
        "skip_existing": args.skip_existing,
        "is_resume": args.is_resume,
        "resume_strategy": args.resume_strategy,
        "source_listing_crawl_job_id": args.source_listing_crawl_job_id,
    }


def _build_manual_action_payload(
    args,
    exc: ManualActionRequiredError,
    *,
    crawl_phase: str,
    source_listing_crawl_job_id: str | None,
) -> dict[str, Any]:
    payload = exc.to_payload(
        crawl_mode=args.crawl_mode,
        browser_channel=settings.jobsdb_headed_browser_channel,
        browser_profile_path=settings.jobsdb_headed_browser_user_data_dir,
    )
    resume_context = dict(payload.get("resume_context") or {})
    resume_context.setdefault("crawl_phase", crawl_phase)
    resume_context.setdefault("crawl_mode", args.crawl_mode)
    resume_context.setdefault("category_ids", list(args.category_ids))
    resume_context.setdefault("skip_existing", args.skip_existing)
    resume_context.setdefault("resume_strategy", args.resume_strategy)
    if source_listing_crawl_job_id:
        resume_context.setdefault("source_listing_crawl_job_id", source_listing_crawl_job_id)
    payload["resume_context"] = resume_context
    return payload


def _resolve_detail_scope(
    args,
    *,
    listing_phase_completed: bool,
) -> tuple[str | None, str]:
    requested_source_listing_crawl_job_id = str(args.source_listing_crawl_job_id or "").strip() or None
    if requested_source_listing_crawl_job_id:
        return requested_source_listing_crawl_job_id, "listing_batch"
    if listing_phase_completed:
        return str(args.crawl_job_id), "current_run_listing_batch"
    return None, "category_backlog"


def _build_detail_request_payload(
    args,
    *,
    source_listing_crawl_job_id: str | None,
) -> dict[str, Any]:
    payload = {
        "crawl_phase": "detail",
        "crawl_mode": args.crawl_mode,
        "source_listing_crawl_job_id": source_listing_crawl_job_id,
        "category_ids": list(args.category_ids),
        "detail_limit": args.detail_limit,
        "detail_statuses": list(args.detail_statuses),
        "skip_existing": args.skip_existing,
    }
    if isinstance(getattr(args, "detail_pacing", None), dict):
        payload["detail_pacing"] = dict(args.detail_pacing)
    return payload


async def _persist_ctgoodjobs_job(*, canonical_job: dict[str, Any]):
    db = SessionLocal()
    try:
        ingest_service = IngestWorkerService()
        company_repository = CompanyRepository()
        job_repository = JobRepository()
        company_data = ingest_service._build_company_data(canonical_job)
        company, _ = company_repository.upsert_company(db, company_data, auto_commit=False)
        ingest_service.project_company_industry(db, company, canonical_job)
        job_data = ingest_service._build_job_data(canonical_job, company.id)
        saved_job, _ = job_repository.upsert_source_job(
            db,
            job_data,
            skip_existing=False,
            auto_commit=False,
        )
        ingest_service.project_source_attributes(db, saved_job, canonical_job)
        db.commit()
        return saved_job.id
    finally:
        db.close()


async def _run_listing_phase_impl(
    args,
    crawl_runtime: CrawlJobRuntime,
    browser_scraper,
    *,
    totals: dict[str, int],
    current_page_context: dict[str, Any],
) -> dict[str, int]:
    cancellation_token = resolve_cancellation_token(args)
    category_lookup = _categories_by_id()

    for category_id in args.category_ids:
        category = _resolve_category(category_lookup, category_id)
        logger.info(
            build_scrape_log_event(
                "SCRAPE_LISTING_CATEGORY_START",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="listing",
                crawl_mode=args.crawl_mode,
                category_id=category.source_classification_id,
                max_pages=args.max_pages,
                skip_existing=args.skip_existing,
            )
        )
        for page_number in range(1, int(args.max_pages) + 1):
            url = category_page_url(category.url, page=page_number)
            current_page_context.update(
                {
                    "category_id": category.source_classification_id,
                    "page": page_number,
                    "total_pages": int(args.max_pages),
                    "url": url,
                }
            )
            page_started_at = time.perf_counter()
            logger.info(
                build_scrape_log_event(
                    "SCRAPE_LISTING_PAGE_START",
                    source=CTGOODJOBS_SOURCE_SITE,
                    crawl_job_id=args.crawl_job_id,
                    crawl_phase="listing",
                    crawl_mode=args.crawl_mode,
                    category_id=category.source_classification_id,
                    current_page=page_number,
                    total_pages=int(args.max_pages),
                )
            )
            cancellation_token.raise_if_cancelled()
            html = await browser_scraper.fetch_page_html(
                url,
                stage="category_page",
                referer="https://jobs.ctgoodjobs.hk/jobs",
            )
            parsed = parse_category_page(
                html,
                category_slug=category.slug,
                source_classification_id=category.source_classification_id,
                source_classification_name=category.name,
                page=page_number,
                url=url,
            )
            page_payloads = []
            job_urls = list(parsed.get("job_urls") or [])
            job_ids = list(parsed.get("job_ids") or [])
            for index, source_job_id in enumerate(job_ids):
                source_url = job_urls[index] if index < len(job_urls) else f"https://jobs.ctgoodjobs.hk/job/{source_job_id}"
                page_payloads.append(
                    {
                        "source_job_id": str(source_job_id),
                        "source_url": source_url,
                        "source_classification_id": category.source_classification_id,
                        "source_classification_name": category.name,
                        "listing_page": page_number,
                        "listing_payload": {
                            "job_id": str(source_job_id),
                            "url": source_url,
                            "source_classification_id": category.source_classification_id,
                            "source_classification_name": category.name,
                            "source_classification_slug": category.slug,
                        },
                    }
                )

            batch_result = crawl_runtime.stage_listing_batch(
                crawl_job_id=args.crawl_job_id,
                source_site=CTGOODJOBS_SOURCE_SITE,
                payloads=page_payloads,
                skip_existing=args.skip_existing,
            )
            totals["pages_processed"] += 1
            totals["job_ids_collected"] += int(batch_result.job_ids_seen)
            totals["raw_job_ids_collected"] += int(batch_result.raw_job_ids_seen)
            totals["listings_staged"] += int(batch_result.rows_staged)
            totals["jobs_skipped_existing"] += int(batch_result.skipped_existing)
            logger.info(
                build_scrape_log_event(
                    "SCRAPE_LISTING_BATCH_STAGED",
                    source=CTGOODJOBS_SOURCE_SITE,
                    crawl_job_id=args.crawl_job_id,
                    crawl_phase="listing",
                    crawl_mode=args.crawl_mode,
                    category_id=category.source_classification_id,
                    current_page=page_number,
                    total_pages=int(args.max_pages),
                    job_ids=batch_result.job_ids_seen,
                    raw_job_ids=batch_result.raw_job_ids_seen,
                    listings_staged=batch_result.rows_staged,
                    jobs_skipped_existing=batch_result.skipped_existing,
                    elapsed_ms=max(
                        int((time.perf_counter() - page_started_at) * 1000),
                        0,
                    ),
                    cumulative_pages=totals["pages_processed"],
                    cumulative_job_ids=totals["job_ids_collected"],
                    cumulative_raw_job_ids=totals["raw_job_ids_collected"],
                    cumulative_listings_staged=totals["listings_staged"],
                    cumulative_skipped=totals["jobs_skipped_existing"],
                )
            )
            crawl_runtime.write_progress_event(
                crawl_job_id=args.crawl_job_id,
                event_type="crawl.page_processed",
                emitted_by="ctgoodjobs-crawl",
                payload={
                    "phase": 1,
                    "category_id": category.source_classification_id,
                    "current_page": page_number,
                    "total_pages": int(args.max_pages),
                    "job_ids_collected": totals["job_ids_collected"],
                    "raw_job_ids_collected": totals["raw_job_ids_collected"],
                    "listings_staged": totals["listings_staged"],
                    "jobs_skipped_existing": totals["jobs_skipped_existing"],
                },
            )

    crawl_runtime.write_progress_event(
        crawl_job_id=args.crawl_job_id,
        event_type="listing_completed",
        emitted_by="ctgoodjobs-crawl",
        payload={
            "phase": 1,
            "pages_processed": totals["pages_processed"],
            "job_ids_collected": totals["job_ids_collected"],
            "raw_job_ids_collected": totals["raw_job_ids_collected"],
            "listings_staged": totals["listings_staged"],
            "jobs_skipped_existing": totals["jobs_skipped_existing"],
            "detail_target_rows": totals["listings_staged"],
            "message": "Listing phase completed; detail phase will continue.",
        },
    )
    return totals


async def _run_listing_phase(
    args,
    crawl_runtime: CrawlJobRuntime,
    browser_scraper,
) -> dict[str, int]:
    totals = {
        "pages_processed": 0,
        "job_ids_collected": 0,
        "raw_job_ids_collected": 0,
        "listings_staged": 0,
        "jobs_skipped_existing": 0,
    }
    current_page_context: dict[str, Any] = {}
    phase_started_at = time.perf_counter()
    outcome = "completed"
    try:
        return await _run_listing_phase_impl(
            args,
            crawl_runtime,
            browser_scraper,
            totals=totals,
            current_page_context=current_page_context,
        )
    except ManualActionRequiredError as exc:
        outcome = "manual_action_required"
        logger.warning(
            build_scrape_log_event(
                "SCRAPE_LISTING_MANUAL_ACTION",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="listing",
                crawl_mode=args.crawl_mode,
                category_id=current_page_context.get("category_id"),
                current_page=current_page_context.get("page"),
                total_pages=current_page_context.get("total_pages"),
                classification=exc.classification,
                code=exc.code,
                stage=exc.stage,
                blocked_url=exc.blocked_url,
                cumulative_pages=totals["pages_processed"],
                cumulative_job_ids=totals["job_ids_collected"],
                cumulative_raw_job_ids=totals["raw_job_ids_collected"],
                cumulative_listings_staged=totals["listings_staged"],
            )
        )
        raise
    except Exception as exc:
        outcome = "failed"
        logger.warning(
            build_scrape_log_event(
                "SCRAPE_LISTING_PAGE_FAIL",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="listing",
                crawl_mode=args.crawl_mode,
                category_id=current_page_context.get("category_id"),
                current_page=current_page_context.get("page"),
                total_pages=current_page_context.get("total_pages"),
                error_type=type(exc).__name__,
                cumulative_pages=totals["pages_processed"],
                cumulative_job_ids=totals["job_ids_collected"],
                cumulative_raw_job_ids=totals["raw_job_ids_collected"],
                cumulative_listings_staged=totals["listings_staged"],
            )
        )
        raise
    finally:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_LISTING_DONE",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="listing",
                crawl_mode=args.crawl_mode,
                outcome=outcome,
                elapsed_ms=max(
                    int((time.perf_counter() - phase_started_at) * 1000),
                    0,
                ),
                pages_processed=totals["pages_processed"],
                job_ids_collected=totals["job_ids_collected"],
                raw_job_ids_collected=totals["raw_job_ids_collected"],
                listings_staged=totals["listings_staged"],
                jobs_skipped_existing=totals["jobs_skipped_existing"],
            )
        )


async def _run_detail_phase(
    args,
    crawl_runtime: CrawlJobRuntime,
    browser_scraper,
    *,
    source_listing_crawl_job_id: str | None,
    detail_scope: str,
) -> dict[str, int]:
    cancellation_token = resolve_cancellation_token(args)
    phase_started_at = time.perf_counter()
    try:
        detail_targets = crawl_runtime.load_detail_targets(
            source_site=CTGOODJOBS_SOURCE_SITE,
            request_payload=_build_detail_request_payload(
                args,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
            ),
            detail_crawl_job_id=args.crawl_job_id,
        )
    except Exception as exc:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_DONE",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="detail",
                crawl_mode=args.crawl_mode,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_scope=detail_scope,
                outcome="failed",
                elapsed_ms=max(
                    int((time.perf_counter() - phase_started_at) * 1000),
                    0,
                ),
                detail_target_rows=0,
                processed=0,
                succeeded=0,
                failed=0,
                saved=0,
                error_type=type(exc).__name__,
            )
        )
        raise
    logger.info(
        build_scrape_log_event(
            "SCRAPE_DETAIL_TARGETS_LOADED",
            source=CTGOODJOBS_SOURCE_SITE,
            crawl_job_id=args.crawl_job_id,
            crawl_phase="detail",
            crawl_mode=args.crawl_mode,
            source_listing_crawl_job_id=source_listing_crawl_job_id,
            detail_scope=detail_scope,
            detail_selected_rows=detail_targets.selected_rows,
            detail_skipped_existing_rows=detail_targets.skipped_existing_rows,
            detail_target_rows=detail_targets.target_rows,
        )
    )
    counts = {
        "selected_rows": int(detail_targets.selected_rows),
        "skipped_existing_rows": int(detail_targets.skipped_existing_rows),
        "target_rows": int(detail_targets.target_rows),
        "completed": 0,
        "failed": 0,
        "terminal_unavailable": 0,
        "manual_action_required": 0,
    }
    last_content_anomaly_reason: str | None = None

    def log_detail_done(outcome: str) -> None:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_DONE",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="detail",
                crawl_mode=args.crawl_mode,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_scope=detail_scope,
                outcome=outcome,
                elapsed_ms=max(
                    int((time.perf_counter() - phase_started_at) * 1000),
                    0,
                ),
                detail_selected_rows=counts["selected_rows"],
                detail_skipped_existing_rows=counts["skipped_existing_rows"],
                detail_target_rows=counts["target_rows"],
                processed=(
                    counts["completed"]
                    + counts["failed"]
                    + counts["terminal_unavailable"]
                    + counts["manual_action_required"]
                ),
                succeeded=counts["completed"],
                failed=counts["failed"],
                terminal_unavailable=counts["terminal_unavailable"],
                manual_action_required=counts["manual_action_required"],
                saved=counts["completed"],
            )
        )

    def record_failure(*, exc: Exception, index: int, target, item_started_at: float) -> None:
        crawl_runtime.mark_detail_failed(
            listing_id=target["listing_id"],
            detail_crawl_job_id=args.crawl_job_id,
            error_message=str(exc),
        )
        counts["failed"] += 1
        logger.warning(
            build_scrape_log_event(
                "SCRAPE_DETAIL_ITEM_FAIL",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="detail",
                crawl_mode=args.crawl_mode,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_index=index,
                detail_total=detail_targets.target_rows,
                source_job_id=target["source_job_id"],
                error_type=type(exc).__name__,
                anomaly_reason=(
                    exc.reason if isinstance(exc, InvalidIngestPayloadError) else None
                ),
                elapsed_ms=max(int((time.perf_counter() - item_started_at) * 1000), 0),
                outcome="failed",
                cumulative_processed=(
                    counts["completed"]
                    + counts["failed"]
                    + counts["terminal_unavailable"]
                ),
                cumulative_succeeded=counts["completed"],
                cumulative_failed=counts["failed"],
                cumulative_terminal_unavailable=counts["terminal_unavailable"],
                cumulative_saved=counts["completed"],
            )
        )

    def pause_for_manual_action(
        *,
        exc: ManualActionRequiredError,
        index: int,
        target,
        item_started_at: float,
    ) -> dict[str, int]:
        crawl_runtime.mark_detail_manual_action_required(
            listing_id=target["listing_id"],
            detail_crawl_job_id=args.crawl_job_id,
            error_message=exc.message,
        )
        logger.warning(
            build_scrape_log_event(
                "SCRAPE_DETAIL_ITEM_MANUAL_ACTION",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="detail",
                crawl_mode=args.crawl_mode,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_index=index,
                detail_total=detail_targets.target_rows,
                source_job_id=target["source_job_id"],
                stage=exc.stage,
                blocked_url=exc.blocked_url,
                classification=exc.classification,
                code=exc.code,
                reason=exc.evidence.get("reason"),
                consecutive_count=exc.evidence.get("consecutive_count"),
                elapsed_ms=max(int((time.perf_counter() - item_started_at) * 1000), 0),
                outcome="manual_action_required",
                cumulative_processed=(
                    counts["completed"]
                    + counts["failed"]
                    + counts["terminal_unavailable"]
                    + 1
                ),
                cumulative_succeeded=counts["completed"],
                cumulative_failed=counts["failed"],
                cumulative_terminal_unavailable=counts["terminal_unavailable"],
                cumulative_manual_action=1,
                cumulative_saved=counts["completed"],
            )
        )
        crawl_runtime.mark_manual_action_required(
            crawl_job_id=args.crawl_job_id,
            source_site=CTGOODJOBS_SOURCE_SITE,
            request_payload=_build_detail_request_payload(
                args,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
            ),
            payload=_build_manual_action_payload(
                args,
                exc,
                crawl_phase="detail",
                source_listing_crawl_job_id=source_listing_crawl_job_id,
            ),
            error_message=exc.message,
        )
        counts["manual_action_required"] = 1
        log_detail_done("manual_action_required")
        return counts

    if detail_targets.target_rows == 0:
        logger.warning(
            build_scrape_log_event(
                "SCRAPE_DETAIL_TARGETS_EMPTY",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_scope=detail_scope,
                categories=",".join(str(category_id) for category_id in args.category_ids),
                detail_statuses=",".join(str(status) for status in args.detail_statuses),
                detail_limit=args.detail_limit,
            )
        )
        log_detail_done("empty")
        return counts
    category_lookup = _categories_by_id()

    for index, target in enumerate(detail_targets.targets, start=1):
        cancellation_token.raise_if_cancelled()
        item_started_at = time.perf_counter()
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_ITEM_START",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="detail",
                crawl_mode=args.crawl_mode,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_index=index,
                detail_total=detail_targets.target_rows,
                source_job_id=target["source_job_id"],
                listing_id=target["listing_id"],
            )
        )
        crawl_runtime.mark_detail_running(
            listing_id=target["listing_id"],
            detail_crawl_job_id=args.crawl_job_id,
        )
        listing_payload = dict(target.get("listing_payload") or {})
        category_id = str(
            target.get("source_classification_id")
            or listing_payload.get("source_classification_id")
            or ""
        ).strip()
        try:
            category = _resolve_category(category_lookup, category_id)
            cancellation_token.raise_if_cancelled()
            html = await browser_scraper.fetch_page_html(
                target["source_url"],
                stage="detail_page",
                referer=target["source_url"],
            )
            detail_job = parse_detail_page(
                html,
                source_classification_id=category.source_classification_id,
                source_classification_name=category.name,
                source_classification_slug=category.slug,
                url=target["source_url"],
            )
            merged = merge_ctgoodjobs_job(
                category={
                    "source_classification_id": category.source_classification_id,
                    "name": category.name,
                    "slug": category.slug,
                },
                list_job=listing_payload,
                detail_job=detail_job,
            )
            canonical = build_ctgoodjobs_canonical_job(merged).to_dict()
            saved_job_id = await _persist_ctgoodjobs_job(canonical_job=canonical)
            crawl_runtime.mark_detail_completed(
                listing_id=target["listing_id"],
                detail_crawl_job_id=args.crawl_job_id,
                detail_payload=canonical["raw_data"],
                published_job_id=saved_job_id,
            )
            counts["completed"] += 1
            last_content_anomaly_reason = None
            logger.info(
                build_scrape_log_event(
                    "SCRAPE_DETAIL_ITEM_OK",
                    source=CTGOODJOBS_SOURCE_SITE,
                    crawl_job_id=args.crawl_job_id,
                    crawl_phase="detail",
                    crawl_mode=args.crawl_mode,
                    source_listing_crawl_job_id=source_listing_crawl_job_id,
                    detail_index=index,
                    detail_total=detail_targets.target_rows,
                    source_job_id=target["source_job_id"],
                    published_job_id=saved_job_id,
                    elapsed_ms=max(
                        int((time.perf_counter() - item_started_at) * 1000),
                        0,
                    ),
                    outcome="success",
                    cumulative_processed=(
                        counts["completed"] + counts["failed"]
                    ),
                    cumulative_succeeded=counts["completed"],
                    cumulative_failed=counts["failed"],
                    cumulative_saved=counts["completed"],
                )
            )
        except ManualActionRequiredError as exc:
            return pause_for_manual_action(
                exc=exc,
                index=index,
                target=target,
                item_started_at=item_started_at,
            )
        except CrawlCancellationRequested:
            raise
        except CTGoodJobsTerminalUnavailableError as exc:
            last_content_anomaly_reason = None
            crawl_runtime.mark_detail_terminal_unavailable(
                listing_id=target["listing_id"],
                detail_crawl_job_id=args.crawl_job_id,
                error_message=str(exc),
            )
            counts["terminal_unavailable"] += 1
            logger.warning(
                build_scrape_log_event(
                    "SCRAPE_DETAIL_ITEM_FAIL",
                    source=CTGOODJOBS_SOURCE_SITE,
                    crawl_job_id=args.crawl_job_id,
                    crawl_phase="detail",
                    crawl_mode=args.crawl_mode,
                    source_listing_crawl_job_id=source_listing_crawl_job_id,
                    detail_index=index,
                    detail_total=detail_targets.target_rows,
                    source_job_id=target["source_job_id"],
                    classification="terminal_unavailable",
                    reason=exc.reason,
                    status_code=exc.status_code,
                    elapsed_ms=max(int((time.perf_counter() - item_started_at) * 1000), 0),
                    outcome="terminal_unavailable",
                    cumulative_processed=(
                        counts["completed"]
                        + counts["failed"]
                        + counts["terminal_unavailable"]
                    ),
                    cumulative_succeeded=counts["completed"],
                    cumulative_failed=counts["failed"],
                    cumulative_terminal_unavailable=counts["terminal_unavailable"],
                    cumulative_saved=counts["completed"],
                )
            )
        except InvalidIngestPayloadError as exc:
            if (
                exc.reason in CONTENT_ANOMALY_REASONS
                and last_content_anomaly_reason == exc.reason
            ):
                manual_exc = build_session_recovery_manual_action(
                    source_site=CTGOODJOBS_SOURCE_SITE,
                    stage="detail_page",
                    blocked_url=target["source_url"],
                    referer=target["source_url"],
                    classification="content_anomaly",
                    evidence={"reason": exc.reason, "consecutive_count": 2},
                )
                return pause_for_manual_action(
                    exc=manual_exc,
                    index=index,
                    target=target,
                    item_started_at=item_started_at,
                )
            last_content_anomaly_reason = (
                exc.reason if exc.reason in CONTENT_ANOMALY_REASONS else None
            )
            record_failure(
                exc=exc,
                index=index,
                target=target,
                item_started_at=item_started_at,
            )
        except Exception as exc:
            last_content_anomaly_reason = None
            record_failure(
                exc=exc,
                index=index,
                target=target,
                item_started_at=item_started_at,
            )

        crawl_runtime.write_progress_event(
            crawl_job_id=args.crawl_job_id,
            event_type="crawl.detail_progress",
            emitted_by="ctgoodjobs-crawl",
            payload={
                "phase": 2,
                "detail_ok": counts["completed"],
                "detail_fail": counts["failed"],
                "detail_unavailable": counts["terminal_unavailable"],
                "detail_manual_action": counts["manual_action_required"],
                "detail_total": counts["target_rows"],
                "detail_index": index,
                "detail_selected_rows": counts["selected_rows"],
                "detail_skipped_existing_rows": counts["skipped_existing_rows"],
                "detail_target_rows": counts["target_rows"],
            },
        )

    log_detail_done("completed")
    return counts


async def main(argv: Sequence[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(list(argv) if argv is not None else None)
    args.category_ids = _parse_category_ids(args.category_ids)
    args.detail_statuses = _parse_detail_statuses(args.detail_statuses)
    args.crawl_job_id = str(args.crawl_job_id or uuid4())
    request_payload, source_site = _load_request_payload(args.crawl_job_id)
    _apply_request_payload_defaults(args, request_payload)
    if str(args.crawl_mode).strip().lower() != "headed":
        raise RuntimeError("CTgoodjobs supports headed crawl mode only")
    args.cancellation_token = CrawlCancellationToken(
        crawl_job_id=args.crawl_job_id,
        execution_generation=args.execution_generation or None,
    )
    if str(source_site).strip().lower() != CTGOODJOBS_SOURCE_SITE:
        logger.warning(
            "CTGoodJobs executor received source_site=%s; continuing with ctgoodjobs runtime",
            source_site,
        )
    logger.info(
        build_scrape_log_event(
            "SCRAPE_EXECUTOR_START",
            source=CTGOODJOBS_SOURCE_SITE,
            crawl_job_id=args.crawl_job_id,
            crawl_phase=args.crawl_phase,
            crawl_mode=args.crawl_mode,
            categories=len(args.category_ids),
            detail_limit=args.detail_limit,
            source_listing_crawl_job_id=args.source_listing_crawl_job_id or None,
            is_resume=args.is_resume,
            resume_strategy=args.resume_strategy,
            skip_existing=args.skip_existing,
        )
    )

    crawl_runtime = CrawlJobRuntime()
    try:
        args.cancellation_token.raise_if_cancelled()
    except CrawlCancellationRequested:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_EXECUTOR_CANCELLED",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase=args.crawl_phase,
                crawl_mode=args.crawl_mode,
            )
        )
        return 0
    crawl_runtime.mark_started(
        crawl_job_id=args.crawl_job_id,
        source_site=CTGOODJOBS_SOURCE_SITE,
        payload={
            "crawl_phase": args.crawl_phase,
            "crawl_mode": args.crawl_mode,
            "category_ids": list(args.category_ids),
        },
    )

    listing_summary = {
        "pages_processed": 0,
        "job_ids_collected": 0,
        "raw_job_ids_collected": 0,
        "listings_staged": 0,
        "jobs_skipped_existing": 0,
    }
    source_listing_crawl_job_id, detail_scope = _resolve_detail_scope(
        args,
        listing_phase_completed=False,
    )

    try:
        args.cancellation_token.raise_if_cancelled()
        detail_pacing_controller = build_detail_pacing_controller(
            request_payload={"detail_pacing": getattr(args, "detail_pacing", None)},
            crawl_job_id=args.crawl_job_id,
            crawl_runtime=crawl_runtime,
            cancellation_owner=args,
        )
        async with CTGoodJobsBrowserPageScraper(
            request_payload=_build_browser_request_payload(args),
            cancellation_token=args.cancellation_token,
            detail_pacing_controller=detail_pacing_controller,
        ) as browser_scraper:
            if args.crawl_phase in {"full", "listing"}:
                listing_summary = await _run_listing_phase(args, crawl_runtime, browser_scraper)
                source_listing_crawl_job_id, detail_scope = _resolve_detail_scope(
                    args,
                    listing_phase_completed=True,
                )

            detail_summary = {
                "selected_rows": 0,
                "skipped_existing_rows": 0,
                "target_rows": 0,
                "completed": 0,
                "failed": 0,
                "manual_action_required": 0,
            }
            if args.crawl_phase in {"full", "detail"}:
                logger.info(
                    build_scrape_log_event(
                        "SCRAPE_DETAIL_SCOPE_RESOLVED",
                        source=CTGOODJOBS_SOURCE_SITE,
                        crawl_job_id=args.crawl_job_id,
                        source_listing_crawl_job_id=source_listing_crawl_job_id,
                        detail_scope=detail_scope,
                        categories=",".join(str(category_id) for category_id in args.category_ids),
                        detail_statuses=",".join(str(status) for status in args.detail_statuses),
                        detail_limit=args.detail_limit,
                    )
                )
                detail_summary = await _run_detail_phase(
                    args,
                    crawl_runtime,
                    browser_scraper,
                    source_listing_crawl_job_id=source_listing_crawl_job_id,
                    detail_scope=detail_scope,
                )
                if detail_summary.get("manual_action_required"):
                    logger.warning(
                        build_scrape_log_event(
                            "SCRAPE_EXECUTOR_MANUAL_ACTION",
                            source=CTGOODJOBS_SOURCE_SITE,
                            crawl_job_id=args.crawl_job_id,
                            crawl_phase="detail",
                            crawl_mode=args.crawl_mode,
                            source_listing_crawl_job_id=(
                                source_listing_crawl_job_id
                            ),
                        )
                    )
                    return 1

            crawl_runtime.mark_completed(
                crawl_job_id=args.crawl_job_id,
                source_site=CTGOODJOBS_SOURCE_SITE,
                payload={
                    "crawl_phase": args.crawl_phase,
                    "crawl_mode": args.crawl_mode,
                    "category_ids": list(args.category_ids),
                },
                metrics={
                    "pages_processed": listing_summary["pages_processed"],
                    "job_ids_collected": listing_summary["job_ids_collected"],
                    "raw_job_ids_collected": listing_summary["raw_job_ids_collected"],
                    "listings_staged": listing_summary["listings_staged"],
                    "jobs_skipped_existing": listing_summary["jobs_skipped_existing"],
                    "detail_selected_rows": detail_summary["selected_rows"],
                    "detail_skipped_existing_rows": detail_summary["skipped_existing_rows"],
                    "detail_target_rows": detail_summary["target_rows"],
                    "detail_completed": detail_summary["completed"],
                    "detail_failed": detail_summary["failed"],
                    "items_emitted": detail_summary["completed"],
                    "jobs_saved": detail_summary["completed"],
                },
            )
            logger.info(
                build_scrape_log_event(
                    "SCRAPE_EXECUTOR_DONE",
                    source=CTGOODJOBS_SOURCE_SITE,
                    crawl_job_id=args.crawl_job_id,
                    crawl_phase=args.crawl_phase,
                    crawl_mode=args.crawl_mode,
                    job_ids_collected=listing_summary["job_ids_collected"],
                    raw_job_ids_collected=listing_summary["raw_job_ids_collected"],
                    listings_staged=listing_summary["listings_staged"],
                    detail_target_rows=detail_summary["target_rows"],
                    detail_completed=detail_summary["completed"],
                    detail_failed=detail_summary["failed"],
                )
            )
            return 0
    except CrawlCancellationRequested:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_EXECUTOR_CANCELLED",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase=args.crawl_phase,
                crawl_mode=args.crawl_mode,
            )
        )
        return 0
    except ManualActionRequiredError as exc:
        resume_crawl_phase = "detail" if args.crawl_phase == "detail" else "listing"
        resume_source_listing_crawl_job_id = source_listing_crawl_job_id
        if resume_crawl_phase == "listing":
            resume_source_listing_crawl_job_id = str(args.crawl_job_id)
        logger.warning(
            build_scrape_log_event(
                "SCRAPE_EXECUTOR_MANUAL_ACTION",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase=resume_crawl_phase,
                crawl_mode=args.crawl_mode,
                classification=exc.classification,
                code=exc.code,
                stage=exc.stage,
                blocked_url=exc.blocked_url,
            )
        )
        crawl_runtime.mark_manual_action_required(
            crawl_job_id=args.crawl_job_id,
            source_site=CTGOODJOBS_SOURCE_SITE,
            request_payload=_build_browser_request_payload(args),
            payload=_build_manual_action_payload(
                args,
                exc,
                crawl_phase=resume_crawl_phase,
                source_listing_crawl_job_id=resume_source_listing_crawl_job_id,
            ),
            error_message=exc.message,
        )
        return 1
    except Exception as exc:
        logger.exception(
            build_scrape_log_event(
                "SCRAPE_EXECUTOR_FAIL",
                source=CTGOODJOBS_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase=args.crawl_phase,
                crawl_mode=args.crawl_mode,
                error_type=type(exc).__name__,
            )
        )
        crawl_runtime.mark_failed(
            crawl_job_id=args.crawl_job_id,
            source_site=CTGOODJOBS_SOURCE_SITE,
            error_message=str(exc),
            payload={
                "crawl_phase": args.crawl_phase,
                "crawl_mode": args.crawl_mode,
                "category_ids": list(args.category_ids),
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
