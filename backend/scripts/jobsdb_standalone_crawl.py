#!/usr/bin/env python3
"""Standalone JobsDB crawl executor using app-layer scrapers and shared runtime state."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sys
import time
from typing import Any, AsyncIterator, Sequence
from uuid import uuid4

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("jobsdb-crawl")

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
from app.scraper.category_scraper import CategoryListScraper  # noqa: E402
from app.scraper.job_detail_scraper import JobDetailScraper  # noqa: E402
from app.scraper.jobsdb_browser_detail_scraper import JobsDBBrowserDetailScraper  # noqa: E402
from app.scraper.log_events import build_scrape_log_event  # noqa: E402
from app.scraper.manual_action import (  # noqa: E402
    ManualActionRequiredError,
    RESUME_STRATEGY_FRESH_PROFILE,
    SUPPORTED_RESUME_STRATEGIES,
)
from app.services.crawl_job_runtime import CrawlJobRuntime, ListingBatchPersistResult  # noqa: E402
from app.services.crawl_cancellation_token import (  # noqa: E402
    CrawlCancellationRequested,
    CrawlCancellationToken,
    resolve_cancellation_token,
)
from app.services.detail_pacing import build_detail_pacing_controller  # noqa: E402
from app.sources.contracts import build_jobsdb_canonical_job  # noqa: E402
from app.source_catalog.runtime import load_published_query_plan  # noqa: E402
from app.workers.run_ingest_worker import IngestWorkerService  # noqa: E402

JOBSDB_SOURCE_SITE = "jobsdb"
DEFAULT_DETAIL_STATUSES = ["pending", "manual_action_required"]


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone JobsDB crawler")
    parser.add_argument("--crawl-job-id", type=str, default="")
    parser.add_argument("--execution-generation", type=str, default="")
    parser.add_argument("--category-ids", type=str, default="")
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--detail-limit", type=int, default=100)
    parser.add_argument("--crawl-mode", choices=["headless", "headed"], default="headless")
    parser.add_argument("--crawl-phase", choices=["full", "listing", "detail"], default="full")
    parser.add_argument("--source-listing-crawl-job-id", type=str, default="")
    parser.add_argument("--detail-statuses", type=str, default="pending,manual_action_required")
    parser.add_argument(
        "--resume-strategy",
        choices=list(SUPPORTED_RESUME_STRATEGIES),
        default=RESUME_STRATEGY_FRESH_PROFILE,
    )
    parser.add_argument("--skip-existing", action="store_true", default=False)
    parser.add_argument("--is-resume", action="store_true", default=False)
    return parser


def _load_request_payload(crawl_job_id: str) -> tuple[dict[str, Any], str]:
    db = SessionLocal()
    try:
        startup = load_legacy_worker_startup_input(
            db,
            crawl_job_id=crawl_job_id,
            default_source_site=JOBSDB_SOURCE_SITE,
        )
        return startup.request_payload, startup.source_site
    finally:
        db.close()


def _parse_category_ids(raw_value) -> list[int | str]:
    raw_items = (
        str(raw_value or "").split(",")
        if isinstance(raw_value, str)
        else raw_value or []
    )
    category_ids: list[int | str] = []
    for raw_item in raw_items:
        value = str(raw_item).strip()
        if not value:
            continue
        if value.isdigit():
            category_ids.append(int(value))
            continue
        prefix, separator, native_id = value.partition(":")
        if separator and prefix == "jobsdb" and native_id.isdigit():
            category_ids.append(value)
            continue
        raise ValueError(f"Invalid JobsDB Source Classification ID: {value}")
    return category_ids


def _parse_detail_statuses(raw_value: str) -> list[str]:
    statuses = [value.strip() for value in str(raw_value or "").split(",") if value.strip()]
    return statuses or list(DEFAULT_DETAIL_STATUSES)


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
    args.detail_statuses = list(request_payload.get("detail_statuses") or args.detail_statuses)
    args.resume_strategy = str(request_payload.get("resume_strategy") or args.resume_strategy)
    args.skip_existing = bool(request_payload.get("skip_existing"))
    args.is_resume = bool(request_payload.get("is_resume"))
    args.detail_pacing = request_payload.get("detail_pacing")


def _resolve_source_listing_crawl_job_id(args) -> str:
    return str(args.source_listing_crawl_job_id or args.crawl_job_id)


def _build_listing_request_payload(args) -> dict[str, Any]:
    return {
        "crawl_phase": "listing",
        "crawl_mode": args.crawl_mode,
        "category_ids": list(args.category_ids),
        "max_pages": args.max_pages,
        "skip_existing": args.skip_existing,
    }


def _build_detail_request_payload(args) -> dict[str, Any]:
    payload = {
        "crawl_phase": "detail",
        "crawl_mode": args.crawl_mode,
        "source_listing_crawl_job_id": _resolve_source_listing_crawl_job_id(args),
        "category_ids": list(args.category_ids),
        "detail_limit": args.detail_limit,
        "detail_statuses": list(args.detail_statuses),
        "skip_existing": args.skip_existing,
    }
    if isinstance(getattr(args, "detail_pacing", None), dict):
        payload["detail_pacing"] = dict(args.detail_pacing)
    return payload


def _build_manual_action_payload(
    args,
    exc: ManualActionRequiredError,
    *,
    crawl_phase: str,
) -> dict[str, Any]:
    payload = exc.to_payload(
        crawl_mode=args.crawl_mode,
        browser_channel=settings.jobsdb_headed_browser_channel,
        browser_profile_path=settings.jobsdb_headed_browser_user_data_dir,
    )
    resume_context: dict[str, Any] = {
        "crawl_phase": crawl_phase,
        "crawl_mode": args.crawl_mode,
        "category_ids": list(args.category_ids),
        "skip_existing": args.skip_existing,
        "resume_strategy": args.resume_strategy,
    }
    if crawl_phase == "listing":
        resume_context["max_pages"] = args.max_pages
    else:
        resume_context.update(_build_detail_request_payload(args))
    payload["resume_context"] = {
        **resume_context,
        **dict(payload.get("resume_context") or {}),
    }
    return payload


async def run_listing_phase(args, crawl_runtime: CrawlJobRuntime) -> ListingBatchPersistResult:
    query_plan = load_published_query_plan(JOBSDB_SOURCE_SITE, args.category_ids)
    native_category_ids = [int(entry.target.payload["native_id"]) for entry in query_plan.entries]
    classification_by_native = {
        int(entry.target.payload["native_id"]): str(entry.node.classification_id)
        for entry in query_plan.entries
    }
    scraper = CategoryListScraper()
    cancellation_token = resolve_cancellation_token(args)
    if hasattr(scraper, "before_request"):
        scraper.before_request = cancellation_token.raise_if_cancelled
    if hasattr(scraper, "sleep"):
        scraper.sleep = cancellation_token.sleep
    phase_started_at = time.perf_counter()
    pages_processed = 0
    rows_created = 0
    raw_job_ids_collected = 0
    seen_source_job_ids: dict[str, None] = {}
    created_source_job_ids: dict[str, None] = {}
    preexisting_staged_source_job_ids: dict[str, None] = {}
    published_source_job_ids: dict[str, None] = {}
    skipped_existing_source_job_ids: dict[str, None] = {}
    current_page_context: dict[str, Any] = {}
    page_started_at: dict[tuple[int, int], float] = {}
    phase_outcome = "completed"

    async def on_page_start(
        *,
        category_id: int,
        category_name: str,
        page: int,
        total_pages: int,
    ) -> None:
        current_page_context.update(
            {
                "category_id": category_id,
                "category_name": category_name,
                "page": page,
                "total_pages": total_pages,
            }
        )
        page_started_at[(category_id, page)] = time.perf_counter()
        logger.info(
            build_scrape_log_event(
                "SCRAPE_LISTING_PAGE_START",
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="listing",
                crawl_mode=args.crawl_mode,
                category_id=category_id,
                category_name=category_name,
                current_page=page,
                total_pages=total_pages,
            )
        )

    async def stage_page(
        *,
        category_id: int,
        category_name: str,
        page: int,
        total_pages: int,
        jobs: list[dict[str, Any]],
    ) -> None:
        nonlocal pages_processed, rows_created, raw_job_ids_collected
        page_payloads = [
            {
                "source_job_id": source_job_id,
                "source_url": f"https://hk.jobsdb.com/job/{source_job_id}",
                "source_classification_id": classification_by_native[category_id],
                "source_classification_name": None,
                "listing_page": page,
                "listing_payload": dict(job),
            }
            for job in jobs
            if (source_job_id := str(job.get("id") or "").strip())
        ]
        batch_result = crawl_runtime.stage_listing_batch(
            crawl_job_id=args.crawl_job_id,
            source_site=JOBSDB_SOURCE_SITE,
            payloads=page_payloads,
            skip_existing=args.skip_existing,
        )
        pages_processed += 1
        rows_created += int(batch_result.rows_created)
        raw_job_ids_collected += int(batch_result.raw_job_ids_seen)
        for source_job_id in (
            str(payload["source_job_id"]) for payload in page_payloads
        ):
            seen_source_job_ids.setdefault(source_job_id, None)
        for source_job_id in batch_result.created_source_job_ids:
            created_source_job_ids.setdefault(str(source_job_id), None)
        for source_job_id in batch_result.preexisting_staged_source_job_ids:
            preexisting_staged_source_job_ids.setdefault(str(source_job_id), None)
        for source_job_id in batch_result.published_source_job_ids:
            published_source_job_ids.setdefault(str(source_job_id), None)
            if args.skip_existing:
                skipped_existing_source_job_ids.setdefault(str(source_job_id), None)

        started_at = page_started_at.pop((category_id, page), None)
        elapsed_ms = (
            max(int((time.perf_counter() - started_at) * 1000), 0)
            if started_at is not None
            else 0
        )
        logger.info(
            build_scrape_log_event(
                "SCRAPE_LISTING_BATCH_STAGED",
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="listing",
                crawl_mode=args.crawl_mode,
                category_id=category_id,
                category_name=category_name,
                current_page=page,
                total_pages=total_pages,
                elapsed_ms=elapsed_ms,
                job_ids=batch_result.job_ids_seen,
                raw_job_ids=batch_result.raw_job_ids_seen,
                listings_staged=batch_result.rows_staged,
                jobs_skipped_existing=batch_result.skipped_existing,
                cumulative_pages=pages_processed,
                cumulative_job_ids=len(seen_source_job_ids),
                cumulative_raw_job_ids=raw_job_ids_collected,
                cumulative_listings_staged=rows_created,
                cumulative_skipped=len(skipped_existing_source_job_ids),
            )
        )
        crawl_runtime.write_progress_event(
            crawl_job_id=args.crawl_job_id,
            event_type="crawl.page_processed",
            emitted_by="jobsdb-crawl",
            payload={
                "phase": 1,
                "category_id": category_id,
                "current_page": page,
                "total_pages": total_pages,
                "job_ids_collected": len(seen_source_job_ids),
                "raw_job_ids_collected": raw_job_ids_collected,
                "listings_staged": rows_created,
                "jobs_skipped_existing": len(skipped_existing_source_job_ids),
            },
        )

    try:
        for category_id in native_category_ids:
            logger.info(
                build_scrape_log_event(
                    "SCRAPE_LISTING_CATEGORY_START",
                    source=JOBSDB_SOURCE_SITE,
                    crawl_job_id=args.crawl_job_id,
                    crawl_phase="listing",
                    crawl_mode=args.crawl_mode,
                    category_id=category_id,
                    max_pages=args.max_pages,
                    skip_existing=args.skip_existing,
                )
            )
            await scraper.scrape_category(
                category_id,
                max_pages=args.max_pages,
                page_sink=stage_page,
                on_page_start=on_page_start,
            )
    except ManualActionRequiredError as exc:
        phase_outcome = "manual_action_required"
        logger.warning(
            build_scrape_log_event(
                "SCRAPE_LISTING_MANUAL_ACTION",
                source=JOBSDB_SOURCE_SITE,
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
                cumulative_pages=pages_processed,
                cumulative_job_ids=len(seen_source_job_ids),
                cumulative_raw_job_ids=raw_job_ids_collected,
                cumulative_listings_staged=rows_created,
            )
        )
        raise
    except Exception as exc:
        phase_outcome = "failed"
        logger.warning(
            build_scrape_log_event(
                "SCRAPE_LISTING_PAGE_FAIL",
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="listing",
                crawl_mode=args.crawl_mode,
                category_id=current_page_context.get("category_id"),
                current_page=current_page_context.get("page"),
                total_pages=current_page_context.get("total_pages"),
                error_type=type(exc).__name__,
                cumulative_pages=pages_processed,
                cumulative_job_ids=len(seen_source_job_ids),
                cumulative_raw_job_ids=raw_job_ids_collected,
                cumulative_listings_staged=rows_created,
            )
        )
        raise
    finally:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_LISTING_DONE",
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="listing",
                crawl_mode=args.crawl_mode,
                outcome=phase_outcome,
                elapsed_ms=max(
                    int((time.perf_counter() - phase_started_at) * 1000),
                    0,
                ),
                categories=len(args.category_ids),
                pages_processed=pages_processed,
                job_ids_collected=len(seen_source_job_ids),
                raw_job_ids_collected=raw_job_ids_collected,
                listings_staged=rows_created,
                jobs_skipped_existing=len(skipped_existing_source_job_ids),
            )
        )

    return ListingBatchPersistResult(
        rows_created=rows_created,
        created_source_job_ids=tuple(created_source_job_ids),
        preexisting_staged_source_job_ids=tuple(
            preexisting_staged_source_job_ids
        ),
        published_source_job_ids=tuple(published_source_job_ids),
        job_ids_seen=len(seen_source_job_ids),
        skipped_existing=len(skipped_existing_source_job_ids),
        raw_job_ids_seen=raw_job_ids_collected,
    )


def _should_use_headed_detail_scraper(args) -> bool:
    return str(args.crawl_mode or "").strip().lower() == "headed" or bool(args.is_resume)


def _build_detail_scraper_request_payload(args) -> dict[str, Any]:
    return {
        "crawl_job_id": args.crawl_job_id,
        "crawl_phase": "detail",
        "crawl_mode": args.crawl_mode,
        "is_resume": args.is_resume,
        "resume_strategy": args.resume_strategy,
        "resume_context": _build_detail_request_payload(args),
    }


@asynccontextmanager
async def _detail_scraper_context(args) -> AsyncIterator[Any]:
    if _should_use_headed_detail_scraper(args):
        async with JobsDBBrowserDetailScraper(
            request_payload=_build_detail_scraper_request_payload(args),
            cancellation_token=resolve_cancellation_token(args),
        ) as scraper:
            yield scraper
        return

    yield JobDetailScraper()


async def run_detail_phase(args, crawl_runtime: CrawlJobRuntime) -> dict[str, int]:
    cancellation_token = resolve_cancellation_token(args)
    detail_pacing_controller = build_detail_pacing_controller(
        request_payload={"detail_pacing": getattr(args, "detail_pacing", None)},
        crawl_job_id=args.crawl_job_id,
        crawl_runtime=crawl_runtime,
        cancellation_owner=args,
    )
    phase_started_at = time.perf_counter()
    try:
        detail_targets = crawl_runtime.load_detail_targets(
            source_site=JOBSDB_SOURCE_SITE,
            request_payload=_build_detail_request_payload(args),
            detail_crawl_job_id=args.crawl_job_id,
        )
    except Exception as exc:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_DONE",
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="detail",
                crawl_mode=args.crawl_mode,
                source_listing_crawl_job_id=(
                    _resolve_source_listing_crawl_job_id(args)
                ),
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
            source=JOBSDB_SOURCE_SITE,
            crawl_job_id=args.crawl_job_id,
            crawl_phase="detail",
            crawl_mode=args.crawl_mode,
            source_listing_crawl_job_id=_resolve_source_listing_crawl_job_id(args),
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
        "manual_action_required": 0,
    }
    if detail_targets.target_rows == 0:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_TARGETS_EMPTY",
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="detail",
                crawl_mode=args.crawl_mode,
                source_listing_crawl_job_id=(
                    _resolve_source_listing_crawl_job_id(args)
                ),
                detail_statuses=",".join(args.detail_statuses),
                detail_limit=args.detail_limit,
            )
        )
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_DONE",
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="detail",
                crawl_mode=args.crawl_mode,
                source_listing_crawl_job_id=(
                    _resolve_source_listing_crawl_job_id(args)
                ),
                outcome="completed",
                elapsed_ms=max(
                    int((time.perf_counter() - phase_started_at) * 1000),
                    0,
                ),
                detail_selected_rows=counts["selected_rows"],
                detail_skipped_existing_rows=counts["skipped_existing_rows"],
                detail_target_rows=0,
                processed=0,
                succeeded=0,
                failed=0,
                manual_action_required=0,
                saved=0,
            )
        )
        return counts
    company_repository = CompanyRepository()
    job_repository = JobRepository()
    ingest_service = None
    db = SessionLocal()
    phase_outcome = "completed"

    try:
        async with _detail_scraper_context(args) as detail_scraper:
            for index, target in enumerate(detail_targets.targets, start=1):
                cancellation_token.raise_if_cancelled()
                item_started_at = time.perf_counter()
                logger.info(
                    build_scrape_log_event(
                        "SCRAPE_DETAIL_ITEM_START",
                        source=JOBSDB_SOURCE_SITE,
                        crawl_job_id=args.crawl_job_id,
                        crawl_phase="detail",
                        crawl_mode=args.crawl_mode,
                        source_listing_crawl_job_id=(
                            _resolve_source_listing_crawl_job_id(args)
                        ),
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
                try:
                    cancellation_token.raise_if_cancelled()
                    if detail_pacing_controller is not None:
                        await detail_pacing_controller.before_attempt()
                    detail = await detail_scraper.fetch_job_detail(target["source_job_id"])
                    if detail is None:
                        raise RuntimeError("JobsDB detail returned no payload")

                    canonical = build_jobsdb_canonical_job(
                        detail,
                        source_url=target["source_url"],
                    ).to_dict()
                    if ingest_service is None:
                        ingest_service = IngestWorkerService()
                    company_data = ingest_service._build_company_data(canonical)
                    company, _ = company_repository.upsert_company(db, company_data, auto_commit=False)
                    ingest_service.project_company_industry(db, company, canonical)
                    job_data = ingest_service._build_job_data(canonical, company.id)
                    saved_job, _ = job_repository.upsert_source_job(
                        db,
                        job_data,
                        skip_existing=False,
                        auto_commit=False,
                    )
                    ingest_service.project_source_attributes(
                        db,
                        saved_job,
                        canonical,
                    )
                    db.commit()
                    published_job_id = saved_job.id
                    crawl_runtime.mark_detail_completed(
                        listing_id=target["listing_id"],
                        detail_crawl_job_id=args.crawl_job_id,
                        detail_payload=canonical["raw_data"],
                        published_job_id=published_job_id,
                    )
                    counts["completed"] += 1
                    logger.info(
                        build_scrape_log_event(
                            "SCRAPE_DETAIL_ITEM_OK",
                            source=JOBSDB_SOURCE_SITE,
                            crawl_job_id=args.crawl_job_id,
                            crawl_phase="detail",
                            crawl_mode=args.crawl_mode,
                            source_listing_crawl_job_id=(
                                _resolve_source_listing_crawl_job_id(args)
                            ),
                            detail_index=index,
                            detail_total=detail_targets.target_rows,
                            source_job_id=target["source_job_id"],
                            published_job_id=published_job_id,
                            elapsed_ms=max(
                                int(
                                    (time.perf_counter() - item_started_at)
                                    * 1000
                                ),
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
                except CrawlCancellationRequested:
                    db.rollback()
                    raise
                except ManualActionRequiredError as exc:
                    db.rollback()
                    crawl_runtime.mark_detail_manual_action_required(
                        listing_id=target["listing_id"],
                        detail_crawl_job_id=args.crawl_job_id,
                        error_message=exc.message,
                    )
                    counts["manual_action_required"] += 1
                    logger.warning(
                        build_scrape_log_event(
                            "SCRAPE_DETAIL_ITEM_MANUAL_ACTION",
                            source=JOBSDB_SOURCE_SITE,
                            crawl_job_id=args.crawl_job_id,
                            crawl_phase="detail",
                            crawl_mode=args.crawl_mode,
                            source_listing_crawl_job_id=(
                                _resolve_source_listing_crawl_job_id(args)
                            ),
                            detail_index=index,
                            detail_total=detail_targets.target_rows,
                            source_job_id=target["source_job_id"],
                            stage=exc.stage,
                            blocked_url=exc.blocked_url,
                            classification=exc.classification,
                            code=exc.code,
                            elapsed_ms=max(
                                int(
                                    (time.perf_counter() - item_started_at)
                                    * 1000
                                ),
                                0,
                            ),
                            outcome="manual_action_required",
                            cumulative_processed=(
                                counts["completed"]
                                + counts["failed"]
                                + counts["manual_action_required"]
                            ),
                            cumulative_succeeded=counts["completed"],
                            cumulative_failed=counts["failed"],
                            cumulative_manual_action=(
                                counts["manual_action_required"]
                            ),
                            cumulative_saved=counts["completed"],
                        )
                    )
                    raise
                except Exception as exc:
                    db.rollback()
                    crawl_runtime.mark_detail_failed(
                        listing_id=target["listing_id"],
                        detail_crawl_job_id=args.crawl_job_id,
                        error_message=str(exc),
                    )
                    counts["failed"] += 1
                    logger.warning(
                        build_scrape_log_event(
                            "SCRAPE_DETAIL_ITEM_FAIL",
                            source=JOBSDB_SOURCE_SITE,
                            crawl_job_id=args.crawl_job_id,
                            crawl_phase="detail",
                            crawl_mode=args.crawl_mode,
                            source_listing_crawl_job_id=(
                                _resolve_source_listing_crawl_job_id(args)
                            ),
                            detail_index=index,
                            detail_total=detail_targets.target_rows,
                            source_job_id=target["source_job_id"],
                            error_type=type(exc).__name__,
                            elapsed_ms=max(
                                int(
                                    (time.perf_counter() - item_started_at)
                                    * 1000
                                ),
                                0,
                            ),
                            outcome="failed",
                            cumulative_processed=(
                                counts["completed"] + counts["failed"]
                            ),
                            cumulative_succeeded=counts["completed"],
                            cumulative_failed=counts["failed"],
                            cumulative_saved=counts["completed"],
                        )
                    )
                crawl_runtime.write_progress_event(
                    crawl_job_id=args.crawl_job_id,
                    event_type="crawl.detail_progress",
                    emitted_by="jobsdb-crawl",
                    payload={
                        "phase": 2,
                        "detail_ok": counts["completed"],
                        "detail_fail": counts["failed"],
                        "detail_total": counts["target_rows"],
                        "detail_index": index,
                        "detail_selected_rows": counts["selected_rows"],
                        "detail_skipped_existing_rows": counts["skipped_existing_rows"],
                        "detail_target_rows": counts["target_rows"],
                    },
                )
    except ManualActionRequiredError:
        phase_outcome = "manual_action_required"
        raise
    except Exception:
        phase_outcome = "failed"
        raise
    finally:
        db.close()
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_DONE",
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase="detail",
                crawl_mode=args.crawl_mode,
                source_listing_crawl_job_id=(
                    _resolve_source_listing_crawl_job_id(args)
                ),
                outcome=phase_outcome,
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
                    + counts["manual_action_required"]
                ),
                succeeded=counts["completed"],
                failed=counts["failed"],
                manual_action_required=counts["manual_action_required"],
                saved=counts["completed"],
            )
        )

    return counts


async def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_argument_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    args.category_ids = _parse_category_ids(args.category_ids)
    args.detail_statuses = _parse_detail_statuses(args.detail_statuses)
    args.crawl_job_id = str(args.crawl_job_id or uuid4())
    request_payload, source_site = _load_request_payload(args.crawl_job_id)
    _apply_request_payload_defaults(args, request_payload)
    args.cancellation_token = CrawlCancellationToken(
        crawl_job_id=args.crawl_job_id,
        execution_generation=args.execution_generation or None,
    )
    if str(source_site).strip().lower() != JOBSDB_SOURCE_SITE:
        logger.warning("JobsDB executor received source_site=%s; continuing with jobsdb runtime", source_site)
    logger.info(
        build_scrape_log_event(
            "SCRAPE_EXECUTOR_START",
            source=JOBSDB_SOURCE_SITE,
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
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase=args.crawl_phase,
                crawl_mode=args.crawl_mode,
            )
        )
        return 0
    crawl_runtime.mark_started(
        crawl_job_id=args.crawl_job_id,
        source_site=JOBSDB_SOURCE_SITE,
        payload={
            "crawl_phase": args.crawl_phase,
            "crawl_mode": args.crawl_mode,
            "category_ids": list(args.category_ids),
        },
    )

    listing_result = None
    detail_result: dict[str, int] | None = None

    try:
        if args.crawl_phase in {"full", "listing"}:
            try:
                listing_result = await run_listing_phase(args, crawl_runtime)
                crawl_runtime.write_progress_event(
                    crawl_job_id=args.crawl_job_id,
                    event_type="listing_completed",
                    emitted_by="jobsdb-crawl",
                    payload={
                        "phase": 1,
                        "job_ids_collected": int(listing_result.job_ids_seen),
                        "raw_job_ids_collected": int(listing_result.raw_job_ids_seen),
                        "listings_staged": int(listing_result.rows_staged),
                        "jobs_skipped_existing": int(listing_result.skipped_existing),
                        "detail_target_rows": int(listing_result.rows_staged),
                        "message": "Listing phase completed; detail phase will continue.",
                    },
                )
            except ManualActionRequiredError as exc:
                logger.warning(
                    build_scrape_log_event(
                        "SCRAPE_EXECUTOR_MANUAL_ACTION",
                        source=JOBSDB_SOURCE_SITE,
                        crawl_job_id=args.crawl_job_id,
                        crawl_phase="listing",
                        crawl_mode=args.crawl_mode,
                        classification=exc.classification,
                        code=exc.code,
                        stage=exc.stage,
                        blocked_url=exc.blocked_url,
                    )
                )
                crawl_runtime.mark_manual_action_required(
                    crawl_job_id=args.crawl_job_id,
                    source_site=JOBSDB_SOURCE_SITE,
                    request_payload=_build_listing_request_payload(args),
                    payload=_build_manual_action_payload(args, exc, crawl_phase="listing"),
                    error_message=exc.message,
                )
                return 1

        if args.crawl_phase in {"full", "detail"}:
            try:
                detail_result = await run_detail_phase(args, crawl_runtime)
            except ManualActionRequiredError as exc:
                logger.warning(
                    build_scrape_log_event(
                        "SCRAPE_EXECUTOR_MANUAL_ACTION",
                        source=JOBSDB_SOURCE_SITE,
                        crawl_job_id=args.crawl_job_id,
                        crawl_phase="detail",
                        crawl_mode=args.crawl_mode,
                        classification=exc.classification,
                        code=exc.code,
                        stage=exc.stage,
                        blocked_url=exc.blocked_url,
                    )
                )
                crawl_runtime.mark_manual_action_required(
                    crawl_job_id=args.crawl_job_id,
                    source_site=JOBSDB_SOURCE_SITE,
                    request_payload=_build_detail_request_payload(args),
                    payload=_build_manual_action_payload(args, exc, crawl_phase="detail"),
                    error_message=exc.message,
                )
                return 1

        metrics = {
            "job_ids_collected": int(listing_result.job_ids_seen) if listing_result is not None else 0,
            "raw_job_ids_collected": int(listing_result.raw_job_ids_seen) if listing_result is not None else 0,
            "listings_staged": int(listing_result.rows_staged) if listing_result is not None else 0,
            "jobs_skipped_existing": int(listing_result.skipped_existing) if listing_result is not None else 0,
            "detail_selected_rows": int(detail_result["selected_rows"]) if detail_result is not None else 0,
            "detail_skipped_existing_rows": int(detail_result["skipped_existing_rows"])
            if detail_result is not None
            else 0,
            "detail_target_rows": int(detail_result["target_rows"]) if detail_result is not None else 0,
            "detail_completed": int(detail_result["completed"]) if detail_result is not None else 0,
            "detail_failed": int(detail_result["failed"]) if detail_result is not None else 0,
            "items_emitted": int(detail_result["completed"]) if detail_result is not None else 0,
            "jobs_saved": int(detail_result["completed"]) if detail_result is not None else 0,
        }
        crawl_runtime.mark_completed(
            crawl_job_id=args.crawl_job_id,
            source_site=JOBSDB_SOURCE_SITE,
            payload={
                "crawl_phase": args.crawl_phase,
                "crawl_mode": args.crawl_mode,
                "category_ids": list(args.category_ids),
            },
            metrics=metrics,
        )
        logger.info(
            build_scrape_log_event(
                "SCRAPE_EXECUTOR_DONE",
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase=args.crawl_phase,
                crawl_mode=args.crawl_mode,
                job_ids_collected=metrics["job_ids_collected"],
                raw_job_ids_collected=metrics["raw_job_ids_collected"],
                listings_staged=metrics["listings_staged"],
                detail_target_rows=metrics["detail_target_rows"],
                detail_completed=metrics["detail_completed"],
                detail_failed=metrics["detail_failed"],
            )
        )
        return 0
    except CrawlCancellationRequested:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_EXECUTOR_CANCELLED",
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase=args.crawl_phase,
                crawl_mode=args.crawl_mode,
            )
        )
        return 0
    except Exception as exc:
        logger.exception(
            build_scrape_log_event(
                "SCRAPE_EXECUTOR_FAIL",
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                crawl_phase=args.crawl_phase,
                crawl_mode=args.crawl_mode,
                error_type=type(exc).__name__,
            )
        )
        crawl_runtime.mark_failed(
            crawl_job_id=args.crawl_job_id,
            source_site=JOBSDB_SOURCE_SITE,
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
