#!/usr/bin/env python3
"""Standalone JobsDB crawl executor using app-layer scrapers and shared runtime state."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sys
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
from app.repositories.crawl_job_repository import CrawlJobRepository  # noqa: E402
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
from app.sources.contracts import build_jobsdb_canonical_job  # noqa: E402
from app.workers.run_ingest_worker import IngestWorkerService  # noqa: E402

JOBSDB_SOURCE_SITE = "jobsdb"
DEFAULT_DETAIL_STATUSES = ["pending", "manual_action_required"]


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone JobsDB crawler")
    parser.add_argument("--crawl-job-id", type=str, default="")
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
        crawl_job = CrawlJobRepository().get_crawl_job_by_id(db, crawl_job_id)
        if crawl_job is None:
            return {}, JOBSDB_SOURCE_SITE
        return dict(crawl_job.request_payload or {}), str(crawl_job.source_site or JOBSDB_SOURCE_SITE)
    finally:
        db.close()


def _parse_category_ids(raw_value: str) -> list[int]:
    return [int(value.strip()) for value in str(raw_value or "").split(",") if value.strip().isdigit()]


def _parse_detail_statuses(raw_value: str) -> list[str]:
    statuses = [value.strip() for value in str(raw_value or "").split(",") if value.strip()]
    return statuses or list(DEFAULT_DETAIL_STATUSES)


def _apply_request_payload_defaults(args, request_payload: dict[str, Any]) -> None:
    if not request_payload:
        return

    args.category_ids = [int(value) for value in (request_payload.get("category_ids") or [])]
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
    return {
        "crawl_phase": "detail",
        "crawl_mode": args.crawl_mode,
        "source_listing_crawl_job_id": _resolve_source_listing_crawl_job_id(args),
        "category_ids": list(args.category_ids),
        "detail_limit": args.detail_limit,
        "detail_statuses": list(args.detail_statuses),
        "skip_existing": args.skip_existing,
    }


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
    scraper = CategoryListScraper()
    page_payloads: list[dict[str, Any]] = []
    pages_processed = 0

    for category_id in args.category_ids:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_LISTING_CATEGORY_START",
                source=JOBSDB_SOURCE_SITE,
                crawl_job_id=args.crawl_job_id,
                category_id=category_id,
                max_pages=args.max_pages,
                skip_existing=args.skip_existing,
            )
        )
        result = await scraper.scrape_category(category_id, max_pages=args.max_pages)
        pages_processed += int(result.get("pages_scraped") or 0)
        for source_job_id in result.get("job_ids", []):
            page_payloads.append(
                {
                    "source_job_id": str(source_job_id),
                    "source_url": f"https://hk.jobsdb.com/job/{source_job_id}",
                    "source_classification_id": str(category_id),
                    "source_classification_name": None,
                    "listing_payload": {},
                }
            )
    batch_result = crawl_runtime.stage_listing_batch(
        crawl_job_id=args.crawl_job_id,
        source_site=JOBSDB_SOURCE_SITE,
        payloads=page_payloads,
        skip_existing=args.skip_existing,
    )
    logger.info(
        build_scrape_log_event(
            "SCRAPE_LISTING_BATCH_STAGED",
            source=JOBSDB_SOURCE_SITE,
            crawl_job_id=args.crawl_job_id,
            categories=len(args.category_ids),
            pages_processed=pages_processed,
            job_ids=batch_result.job_ids_seen,
            listings_staged=batch_result.rows_staged,
            jobs_skipped_existing=batch_result.skipped_existing,
        )
    )
    return batch_result


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
            request_payload=_build_detail_scraper_request_payload(args)
        ) as scraper:
            yield scraper
        return

    yield JobDetailScraper()


async def run_detail_phase(args, crawl_runtime: CrawlJobRuntime) -> dict[str, int]:
    detail_targets = crawl_runtime.load_detail_targets(
        source_site=JOBSDB_SOURCE_SITE,
        request_payload=_build_detail_request_payload(args),
        detail_crawl_job_id=args.crawl_job_id,
    )
    logger.info(
        build_scrape_log_event(
            "SCRAPE_DETAIL_TARGETS_LOADED",
            source=JOBSDB_SOURCE_SITE,
            crawl_job_id=args.crawl_job_id,
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
    }
    company_repository = CompanyRepository()
    job_repository = JobRepository()
    ingest_service = IngestWorkerService()
    db = SessionLocal()

    try:
        async with _detail_scraper_context(args) as detail_scraper:
            for index, target in enumerate(detail_targets.targets, start=1):
                logger.info(
                    build_scrape_log_event(
                        "SCRAPE_DETAIL_ITEM_START",
                        source=JOBSDB_SOURCE_SITE,
                        crawl_job_id=args.crawl_job_id,
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
                    detail = await detail_scraper.fetch_job_detail(target["source_job_id"])
                    if detail is None:
                        raise RuntimeError("JobsDB detail returned no payload")

                    canonical = build_jobsdb_canonical_job(
                        detail,
                        source_url=target["source_url"],
                    ).to_dict()
                    company_data = ingest_service._build_company_data(canonical)
                    company, _ = company_repository.upsert_company(db, company_data, auto_commit=False)
                    job_data = ingest_service._build_job_data(canonical, company.id)
                    saved_job, _ = job_repository.upsert_source_job(
                        db,
                        job_data,
                        skip_existing=False,
                        auto_commit=False,
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
                            detail_index=index,
                            detail_total=detail_targets.target_rows,
                            source_job_id=target["source_job_id"],
                            published_job_id=published_job_id,
                        )
                    )
                except ManualActionRequiredError as exc:
                    db.rollback()
                    crawl_runtime.mark_detail_manual_action_required(
                        listing_id=target["listing_id"],
                        detail_crawl_job_id=args.crawl_job_id,
                        error_message=exc.message,
                    )
                    logger.warning(
                        build_scrape_log_event(
                            "SCRAPE_DETAIL_ITEM_MANUAL_ACTION",
                            source=JOBSDB_SOURCE_SITE,
                            crawl_job_id=args.crawl_job_id,
                            detail_index=index,
                            detail_total=detail_targets.target_rows,
                            source_job_id=target["source_job_id"],
                            stage=exc.stage,
                            blocked_url=exc.blocked_url,
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
                            detail_index=index,
                            detail_total=detail_targets.target_rows,
                            source_job_id=target["source_job_id"],
                            error=exc,
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
    finally:
        db.close()

    return counts


async def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_argument_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    args.category_ids = _parse_category_ids(args.category_ids)
    args.detail_statuses = _parse_detail_statuses(args.detail_statuses)
    args.crawl_job_id = str(args.crawl_job_id or uuid4())
    request_payload, source_site = _load_request_payload(args.crawl_job_id)
    _apply_request_payload_defaults(args, request_payload)
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
                        "listings_staged": int(listing_result.rows_staged),
                        "jobs_skipped_existing": int(listing_result.skipped_existing),
                        "detail_target_rows": int(listing_result.rows_staged),
                        "message": "Listing phase completed; detail phase will continue.",
                    },
                )
            except ManualActionRequiredError as exc:
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
                listings_staged=metrics["listings_staged"],
                detail_target_rows=metrics["detail_target_rows"],
                detail_completed=metrics["detail_completed"],
                detail_failed=metrics["detail_failed"],
            )
        )
        return 0
    except Exception as exc:
        logger.exception("JobsDB crawl failed")
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
