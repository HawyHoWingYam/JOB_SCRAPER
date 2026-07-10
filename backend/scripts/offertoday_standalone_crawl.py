#!/usr/bin/env python3
"""Standalone OfferToday crawler with live progress events.

This path remains wired into the current crawl-job API. The crawl space is
expanded through OfferToday's IT category tree so the backend can collect a
broader set of IT job IDs instead of stopping at a narrow keyword probe.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("offertoday-crawl")

BACKEND = str(Path(__file__).resolve().parents[1])
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.sources.offertoday.constants import (  # noqa: E402
    OFFERTODAY_BASE_URL,
    OFFERTODAY_LISTING_BROWSE_URL,
    build_offertoday_listing_payload,
)
from app.scraper.manual_action import (  # noqa: E402
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
)
from app.scraper.offertoday_pacing import (  # noqa: E402
    pause_after_transient_detail_failure,
    pause_before_detail_request,
)
from app.scraper.log_events import build_scrape_log_event  # noqa: E402
from app.services.crawl_job_runtime import CrawlJobRuntime  # noqa: E402
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime  # noqa: E402
from app.repositories.crawl_job_repository import CrawlJobRepository  # noqa: E402
from app.sources.offertoday.search_space import (  # noqa: E402
    build_offertoday_listing_queries,
    normalize_offertoday_keywords,
)
from app.sources.offertoday.staging import resolve_listing_stage_decision  # noqa: E402
from app.sources.offertoday.parsers import parse_offertoday_listing_response  # noqa: E402

MAX_PAGES_GLOBAL = 9999
DEFAULT_IT_UNIQUE_JOB_TARGET = 3000

# WAF challenge URL fragment — OfferToday redirects here when it detects unusual traffic.
_WAF_CHALLENGE_PATH = "/web/passport/cm/verify"
# How long to wait (seconds) for the user to complete manual WAF verification before giving up.
_WAF_MANUAL_TIMEOUT_SECONDS = 180

_RESUME_STRATEGY_CHOICES = (
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
)


async def _check_and_handle_waf_challenge(page, *, headed: bool, crawl_job_id: str, db: Any) -> bool:
    """Return True if a WAF challenge was detected (and handled or timed out)."""
    try:
        current_url = page.url
    except Exception:
        return False

    if _WAF_CHALLENGE_PATH not in current_url:
        return False

    logger.warning(
        "OfferToday WAF challenge detected at %s. "
        "%s",
        current_url,
        "Waiting for manual verification in browser window." if headed
        else "Headless mode — cannot complete challenge automatically. Retrying warmup.",
    )

    if crawl_job_id and db:
        try:
            from app.models.crawl_job import CrawlJobEvent
            seq = db.query(CrawlJobEvent).filter(CrawlJobEvent.crawl_job_id == crawl_job_id).count()
            _write_progress_event(
                db,
                crawl_job_id=crawl_job_id,
                sequence_no=seq + 1,
                event_type="waf.challenge",
                payload={
                    "message": "WAF security challenge detected. Complete the verification in the browser window to continue.",
                    "challenge_url": current_url,
                    "headed": headed,
                },
            )
            db.commit()
        except Exception as exc:
            logger.warning("Failed to emit waf.challenge event: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

    if not headed:
        return True  # caller will decide whether to abort or retry

    try:
        logger.info("Waiting up to %ds for user to complete WAF verification…", _WAF_MANUAL_TIMEOUT_SECONDS)
        challenge_url = current_url
        await page.wait_for_url(
            lambda current_url: _WAF_CHALLENGE_PATH not in current_url,
            timeout=_WAF_MANUAL_TIMEOUT_SECONDS * 1000,
        )
        logger.info("WAF challenge cleared. Current URL: %s", page.url)
        if crawl_job_id and db:
            try:
                from app.models.crawl_job import CrawlJobEvent

                seq = db.query(CrawlJobEvent).filter(CrawlJobEvent.crawl_job_id == crawl_job_id).count()
                _write_progress_event(
                    db,
                    crawl_job_id=crawl_job_id,
                    sequence_no=seq + 1,
                    event_type="waf.challenge_cleared",
                    payload={
                        "message": "WAF verification completed in the browser window.",
                        "challenge_url": challenge_url,
                        "cleared_url": page.url,
                        "headed": headed,
                    },
                )
                db.commit()
            except Exception as exc:
                logger.warning("Failed to emit waf.challenge_cleared event: %s", exc)
                try:
                    db.rollback()
                except Exception:
                    pass
        await asyncio.sleep(1.5)
        return True
    except Exception as exc:
        logger.warning("WAF wait timed out or failed: %s", exc)

    return True


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone OfferToday crawler")
    parser.add_argument("--category-ids", type=str, default="")
    parser.add_argument("--keywords", type=str, default="")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--crawl-job-id", type=str, default="")
    parser.add_argument("--crawl-phase", choices=["full", "listing", "detail"], default="full")
    parser.add_argument("--source-listing-crawl-job-id", type=str, default="")
    parser.add_argument("--detail-limit", type=int, default=100)
    parser.add_argument("--detail-statuses", type=str, default="pending,manual_action_required")
    parser.add_argument(
        "--headed",
        action="store_true",
        default=False,
        help="Run with a visible browser window so WAF challenges can be completed manually.",
    )
    parser.add_argument(
        "--auth-state",
        default="",
        help=(
            "Path to a Playwright storage_state JSON file produced by offertoday_auth_setup.py. "
            "Loads cookies and localStorage so the crawl starts pre-authenticated, "
            "which reduces WAF challenge frequency."
        ),
    )
    parser.add_argument(
        "--resume-strategy",
        choices=_RESUME_STRATEGY_CHOICES,
        default=RESUME_STRATEGY_FRESH_PROFILE,
        help="How the runtime should create or attach to the browser session.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=False,
        help="Do not queue detail work for jobs that already exist in the database.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Warm the shared browser runtime and run a lightweight listing probe.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        default=False,
        help="Run the runtime check plus one detail probe from the listing response.",
    )
    return parser


def _build_probe_listing_payload(
    *,
    category_ids: list[int],
    keywords: str | Sequence[str] | None,
) -> dict[str, Any]:
    category_id = category_ids[0] if category_ids else None
    normalized_keywords = normalize_offertoday_keywords(keywords)
    return build_offertoday_listing_payload(
        category_id=category_id,
        keyword=normalized_keywords[0] if normalized_keywords else "",
        page=1,
    )


def _load_request_payload(crawl_job_id: str) -> dict[str, Any]:
    if not str(crawl_job_id or "").strip():
        return {}

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        crawl_job = CrawlJobRepository().get_crawl_job_by_id(db, crawl_job_id)
        if crawl_job is None:
            return {}
        return dict(crawl_job.request_payload or {})
    finally:
        db.close()


def _apply_request_payload_defaults(args, request_payload: dict[str, Any]) -> None:
    if not request_payload:
        return

    category_ids = request_payload.get("category_ids") or []
    if category_ids:
        args.category_ids = ",".join(str(category_id) for category_id in category_ids)
    keywords = request_payload.get("keywords")
    if keywords:
        if isinstance(keywords, str):
            args.keywords = keywords
        else:
            args.keywords = ",".join(str(keyword) for keyword in keywords if str(keyword).strip())
    if request_payload.get("max_pages") is not None:
        args.max_pages = int(request_payload["max_pages"])
    if request_payload.get("resume_strategy"):
        args.resume_strategy = str(request_payload["resume_strategy"])
    if request_payload.get("skip_existing") is not None:
        args.skip_existing = bool(request_payload["skip_existing"])
    crawl_mode = str(request_payload.get("crawl_mode") or "").strip().lower()
    args.headed = crawl_mode == "headed" or bool(args.headed)
    requested_phase = str(request_payload.get("crawl_phase") or "").strip().lower()
    if requested_phase in {"listing", "detail"}:
        args.crawl_phase = requested_phase
    else:
        args.crawl_phase = "full"
    if request_payload.get("source_listing_crawl_job_id"):
        args.source_listing_crawl_job_id = str(request_payload["source_listing_crawl_job_id"])
    if request_payload.get("detail_limit") is not None:
        args.detail_limit = int(request_payload["detail_limit"])
    detail_statuses = request_payload.get("detail_statuses")
    if detail_statuses:
        args.detail_statuses = ",".join(str(status) for status in detail_statuses if str(status).strip())


async def _run_runtime_probe(
    *,
    headed: bool,
    auth_state: str,
    resume_strategy: str,
    category_ids: list[int],
    keywords: str | Sequence[str] | None,
    smoke_test: bool,
) -> int:
    listing_payload = _build_probe_listing_payload(category_ids=category_ids, keywords=keywords)
    async with OfferTodayBrowserRuntime(
        headed=headed,
        auth_state_path=auth_state or None,
        resume_strategy=resume_strategy,
    ) as runtime:
        page = runtime._page
        if page is not None:
            await _check_and_handle_waf_challenge(page, headed=headed, crawl_job_id="", db=None)
        try:
            session_check = await runtime.check_session(listing_payload=listing_payload)
        except Exception as exc:
            logger.error("OfferToday runtime check failed: %s", exc)
            return 1
        logger.info(
            "OfferToday runtime check: waf=%s url=%s listing_results=%d",
            session_check.is_waf_challenge,
            session_check.current_url,
            session_check.listing_result_count,
        )
        if session_check.is_waf_challenge:
            logger.error("OfferToday runtime check hit a WAF challenge.")
            return 1
        if not session_check.healthy:
            logger.error("OfferToday runtime check found an unhealthy browser session.")
            return 1
        if not smoke_test:
            return 0

        smoke_result = await runtime.run_smoke_test(
            listing_payload=listing_payload,
            detail_limit=1,
        )
        logger.info(
            "OfferToday smoke test: listing_ok=%s listing_count=%s detail_results=%s",
            smoke_result.get("listing_ok"),
            smoke_result.get("listing_count"),
            smoke_result.get("detail_results"),
        )
        detail_codes = [
            row.get("code")
            for row in smoke_result.get("detail_results", [])
            if isinstance(row, dict)
        ]
        has_detail_success = any(code == 0 for code in detail_codes)
        if not smoke_result.get("listing_ok") or not has_detail_success:
            return 1
        return 0


async def _fetch_listing_json(
    runtime: OfferTodayBrowserRuntime,
    payload: dict[str, Any],
    *,
    listing_url: str | None = None,
) -> dict[str, Any]:
    result = await runtime.fetch_listing_json(payload, listing_url=listing_url)
    return dict(result or {})


async def _fetch_detail_json_with_identifiers(
    runtime: OfferTodayBrowserRuntime,
    *,
    job_id: str,
    encrypted_job_id: str | None = None,
) -> dict[str, Any]:
    result = await runtime.fetch_detail_json(
        job_id=job_id,
        encrypted_job_id=encrypted_job_id,
    )
    return dict(result or {})


def _write_progress_event(db, *, crawl_job_id: str, sequence_no: int, event_type: str, payload: dict) -> None:
    """Write a CrawlJobEvent row visible to the frontend progress API."""
    from app.models.crawl_job import CrawlJobEvent

    evt = CrawlJobEvent(
        crawl_job_id=crawl_job_id,
        sequence_no=sequence_no,
        event_type=event_type,
        payload=payload,
        emitted_by="offertoday-crawl",
        created_at=datetime.now(timezone.utc),
    )
    db.add(evt)


def _persist_listing_checkpoint(
    *,
    crawl_runtime: CrawlJobRuntime,
    crawl_job_id: str,
    search_family: str,
    search_families: list[str],
    category_id: int | None,
    keyword: str,
    current_page: int,
    total_pages: int,
    pending_listing_payloads: list[dict[str, Any]],
    jobs_skipped_existing: int,
    skip_existing: bool,
):
    listing_batch_result = crawl_runtime.stage_listing_batch(
        crawl_job_id=crawl_job_id,
        source_site="offertoday",
        payloads=pending_listing_payloads,
        skip_existing=skip_existing,
    )
    logger.info(
        build_scrape_log_event(
            "SCRAPE_LISTING_BATCH_STAGED",
            source="offertoday",
            crawl_job_id=crawl_job_id,
            search_family=search_family,
            category_id=category_id,
            keyword=keyword,
            current_page=current_page,
            total_pages=total_pages,
            job_ids=listing_batch_result.job_ids_seen,
            listings_staged=listing_batch_result.rows_staged,
            jobs_skipped_existing=jobs_skipped_existing + listing_batch_result.skipped_existing,
        )
    )
    crawl_runtime.write_progress_event(
        crawl_job_id=crawl_job_id,
        event_type="crawl.page_processed",
        emitted_by="offertoday-crawl",
        payload={
            "search_family": search_family,
            "search_families": search_families,
            "category_id": category_id,
            "keyword": keyword,
            "current_page": current_page,
            "total_pages": total_pages,
            "job_ids_collected": listing_batch_result.job_ids_seen,
            "listings_staged": listing_batch_result.rows_staged,
            "jobs_skipped_existing": jobs_skipped_existing + listing_batch_result.skipped_existing,
            "phase": 1,
        },
    )
    return listing_batch_result


async def main() -> None:
    parser = _build_argument_parser()
    args = parser.parse_args()
    _apply_request_payload_defaults(args, _load_request_payload(args.crawl_job_id))
    crawl_phase = str(args.crawl_phase or "full").strip().lower()
    logger.info(
        build_scrape_log_event(
            "SCRAPE_EXECUTOR_START",
            source="offertoday",
            crawl_job_id=args.crawl_job_id or None,
            crawl_phase=crawl_phase,
            crawl_mode="headed" if args.headed else "headless",
            category_ids=args.category_ids or None,
            keywords=args.keywords or None,
            max_pages=args.max_pages,
            detail_limit=args.detail_limit,
            source_listing_crawl_job_id=args.source_listing_crawl_job_id or None,
            resume_strategy=args.resume_strategy,
            skip_existing=args.skip_existing,
        )
    )

    category_ids = [int(c.strip()) for c in args.category_ids.split(",") if c.strip().isdigit()]
    keywords = normalize_offertoday_keywords(args.keywords)
    if args.check or args.smoke_test:
        exit_code = await _run_runtime_probe(
            headed=args.headed,
            auth_state=args.auth_state,
            resume_strategy=args.resume_strategy,
            category_ids=category_ids,
            keywords=keywords,
            smoke_test=args.smoke_test,
        )
        if exit_code != 0:
            raise SystemExit(exit_code)
        return

    page_limit_per_query = min(args.max_pages, MAX_PAGES_GLOBAL)
    listing_tasks = (
        build_offertoday_listing_queries(
            category_ids,
            keywords=keywords or None,
            max_pages_per_query=page_limit_per_query,
        )
        if crawl_phase != "detail"
        else []
    )
    search_families = list(
        dict.fromkeys(
            task["search_family"]
            for task in listing_tasks
            if str(task.get("search_family") or "").strip()
        )
    )
    planned_total_pages = len(listing_tasks)
    is_default_it_crawl = not keywords and any(
        family in {"it_category", "it_keyword"} for family in search_families
    )

    from app.database import SessionLocal
    from app.models.crawl_job import CrawlJob
    from app.models.job import Job
    from app.repositories.company_repository import CompanyRepository
    from app.repositories.job_repository import JobRepository
    from app.sources.contracts import (
        build_offertoday_canonical_job,
        build_offertoday_company_data,
        build_offertoday_job_data,
    )

    db = SessionLocal()
    crawl_runtime = CrawlJobRuntime()
    detail_ok = 0
    detail_fail = 0
    company_repository = CompanyRepository()
    job_repository = JobRepository()
    ip_blocked = False

    if args.crawl_job_id:
        cj_id = args.crawl_job_id
        cj = db.query(CrawlJob).filter(CrawlJob.id == cj_id).first()
        if cj:
            crawl_runtime.mark_started(
                crawl_job_id=cj_id,
                source_site="offertoday",
                payload={"phase": 2 if crawl_phase == "detail" else 1, "source_site": "offertoday"},
                metrics={
                    "pages_processed": 0,
                    "job_ids_collected": 0,
                    "listings_staged": 0,
                    "detail_pending": 0,
                    "items_emitted": 0,
                    "jobs_saved": 0,
                    "search_families": search_families,
                },
            )
            logger.info("Crawl job %s: running", cj_id)
    else:
        cj_id = str(uuid.uuid4())

    seen_ids: set[str] = set()
    listing_count = 0
    new_jobs_count = 0
    jobs_skipped_existing = 0
    page_count = 0
    search_family = ""

    existing_count = db.query(Job).filter(Job.source_site == "offertoday").count()
    logger.info("Existing OfferToday jobs in DB: %d", existing_count)
    logger.info(
        "OfferToday search space: tasks=%d families=%s max_pages_per_query=%d",
        len(listing_tasks),
        ", ".join(search_families) or "[none]",
        page_limit_per_query,
    )

    try:
        auth_state_path = Path(args.auth_state).resolve() if args.auth_state else None
        if auth_state_path and auth_state_path.exists():
            logger.info("Loading auth state from %s", auth_state_path)
        elif args.auth_state:
            logger.warning(
                "Auth state file not found: %s ??starting without pre-loaded session",
                auth_state_path,
            )

        async with OfferTodayBrowserRuntime(
            headed=args.headed,
            auth_state_path=str(auth_state_path) if auth_state_path else None,
            resume_strategy=args.resume_strategy,
        ) as runtime:
            page = runtime._page
            if page is None:
                raise RuntimeError("OfferToday browser runtime did not create a page")

            await _check_and_handle_waf_challenge(
                page, headed=args.headed, crawl_job_id=cj_id, db=db
            )
            logger.info("Warmup complete (url=%s)", page.url)

            exhausted_conditions: set[tuple[str, Any, Any]] = set()
            consecutive_failures = 0
            for task_index, task in enumerate(listing_tasks):
                search_family = str(task.get("search_family") or "").strip() or "category_search"
                category_id = task.get("category_id")
                keyword = str(task.get("keyword") or "")
                page_number = int(task.get("page") or 1)
                condition_key = (search_family, category_id, keyword)
                if condition_key in exhausted_conditions:
                    continue

                payload = build_offertoday_listing_payload(
                    category_id=category_id,
                    keyword=keyword,
                    page=page_number,
                )
                task_listing_url = (
                    OFFERTODAY_LISTING_BROWSE_URL
                    if task.get("endpoint") == "browse"
                    else None
                )
                data = await _fetch_listing_json(
                    runtime,
                    payload,
                    listing_url=task_listing_url,
                )

                if not data or data.get("code") != 0:
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        await _check_and_handle_waf_challenge(
                            page, headed=args.headed, crawl_job_id=cj_id, db=db
                        )
                        consecutive_failures = 0
                    continue

                consecutive_failures = 0

                if task_index > 0 and task_index % 50 == 0:
                    await _check_and_handle_waf_challenge(
                        page, headed=args.headed, crawl_job_id=cj_id, db=db
                    )

                result_list = data.get("data", {}).get("resultList", [])
                if not result_list:
                    exhausted_conditions.add(condition_key)
                    continue

                pending_listing_payloads: list[dict[str, Any]] = []
                for raw_job in result_list:
                    job_id_str = str(raw_job.get("jobId") or "").strip()
                    if not job_id_str or job_id_str in seen_ids:
                        continue
                    seen_ids.add(job_id_str)

                    parsed_listing = parse_offertoday_listing_response(
                        {"code": 0, "data": {"resultList": [raw_job]}}
                    )
                    enriched_listing = parsed_listing[0] if parsed_listing else dict(raw_job)

                    already_in_db = (
                        db.query(Job)
                        .filter(
                            Job.source_site == "offertoday",
                            Job.source_job_id == job_id_str,
                        )
                        .first()
                    )
                    stage_decision = resolve_listing_stage_decision(
                        already_in_db=already_in_db is not None,
                        skip_existing=args.skip_existing,
                    )
                    if stage_decision.is_new_job:
                        new_jobs_count += 1
                    if stage_decision.skipped_existing:
                        jobs_skipped_existing += 1
                        continue

                    pending_listing_payloads.append(
                        {
                            "source_job_id": job_id_str,
                            "source_url": f"{OFFERTODAY_BASE_URL}/hk/job/{job_id_str}",
                            "source_classification_id": str(category_id) if category_id is not None else None,
                            "listing_page": page_number,
                            "listing_payload": enriched_listing,
                        }
                    )

                page_count += 1

                if args.crawl_job_id:
                    listing_batch_result = _persist_listing_checkpoint(
                        crawl_runtime=crawl_runtime,
                        crawl_job_id=cj_id,
                        search_family=search_family,
                        search_families=search_families,
                        category_id=category_id,
                        keyword=keyword,
                        current_page=page_count,
                        total_pages=planned_total_pages,
                        pending_listing_payloads=pending_listing_payloads,
                        jobs_skipped_existing=jobs_skipped_existing,
                        skip_existing=args.skip_existing,
                    )
                    listing_count += listing_batch_result.rows_staged
                    cj = db.query(CrawlJob).filter(CrawlJob.id == cj_id).first()
                    if cj:
                        cj.metrics = {
                            "pages_processed": page_count,
                            "current_page": page_count,
                            "total_pages": planned_total_pages,
                            "job_ids_collected": len(seen_ids),
                            "listings_staged": listing_count,
                            "jobs_skipped_existing": jobs_skipped_existing,
                            "detail_pending": listing_count,
                            "detail_completed": 0,
                            "detail_failed": 0,
                            "items_emitted": 0,
                            "jobs_saved": 0,
                            "search_families": search_families,
                            "search_family": search_family,
                        }
                else:
                    listing_count += len(pending_listing_payloads)

                if page_count % 5 == 0 or page_count == 1:
                    if args.crawl_job_id:
                        cj = db.query(CrawlJob).filter(CrawlJob.id == cj_id).first()
                        if cj:
                            cj.metrics = {
                                "pages_processed": page_count,
                                "current_page": page_count,
                                "total_pages": planned_total_pages,
                                "job_ids_collected": len(seen_ids),
                                "listings_staged": listing_count,
                                "jobs_skipped_existing": jobs_skipped_existing,
                                "detail_pending": listing_count,
                                "items_emitted": 0,
                                "jobs_saved": 0,
                                "search_families": search_families,
                                "search_family": search_family,
                            }
                    db.commit()

                await asyncio.sleep(0.5)

                if is_default_it_crawl and len(seen_ids) >= DEFAULT_IT_UNIQUE_JOB_TARGET:
                    logger.info(
                        "Default IT crawl reached unique target (%d); stopping listing phase.",
                        DEFAULT_IT_UNIQUE_JOB_TARGET,
                    )
                    break

                if not data.get("data", {}).get("hasMore"):
                    exhausted_conditions.add(condition_key)

            if is_default_it_crawl and len(seen_ids) >= DEFAULT_IT_UNIQUE_JOB_TARGET:
                logger.info("Default IT crawl target reached; skipping remaining listing tasks.")

            detail_target_rows = listing_count
            detail_selected_rows = len(seen_ids)
            detail_skipped_existing_rows = jobs_skipped_existing
            detail_targets: list[dict[str, Any]] = []

            if args.crawl_job_id:
                if crawl_phase in {"full", "detail"}:
                    detail_load_result = crawl_runtime.load_detail_targets(
                        source_site="offertoday",
                        request_payload={
                            "crawl_phase": "detail",
                            "crawl_mode": "headed" if args.headed else "headless",
                            "source_listing_crawl_job_id": args.source_listing_crawl_job_id or cj_id,
                            "category_ids": category_ids,
                            "detail_limit": listing_count if crawl_phase == "full" else args.detail_limit,
                            "detail_statuses": [status.strip() for status in str(args.detail_statuses).split(",") if status.strip()],
                            "skip_existing": args.skip_existing,
                        },
                        detail_crawl_job_id=cj_id,
                    )
                    detail_targets = list(detail_load_result.targets)
                    detail_target_rows = int(detail_load_result.target_rows)
                    detail_selected_rows = int(detail_load_result.selected_rows)
                    detail_skipped_existing_rows = int(detail_load_result.skipped_existing_rows)
                    logger.info(
                        build_scrape_log_event(
                            "SCRAPE_DETAIL_TARGETS_LOADED",
                            source="offertoday",
                            crawl_job_id=cj_id,
                            source_listing_crawl_job_id=args.source_listing_crawl_job_id or cj_id,
                            detail_selected_rows=detail_selected_rows,
                            detail_skipped_existing_rows=detail_skipped_existing_rows,
                            detail_target_rows=detail_target_rows,
                        )
                    )

                crawl_runtime.write_progress_event(
                    crawl_job_id=cj_id,
                    emitted_by="offertoday-crawl",
                    event_type="listing_completed",
                    payload={
                        "phase": 1,
                        "search_families": search_families,
                        "pages_processed": page_count,
                        "job_ids_collected": len(seen_ids),
                        "listings_staged": listing_count,
                        "jobs_skipped_existing": jobs_skipped_existing,
                        "detail_selected_rows": detail_selected_rows,
                        "detail_skipped_existing_rows": detail_skipped_existing_rows,
                        "detail_target_rows": detail_target_rows,
                        "detail_pending": detail_target_rows,
                        "message": "Listing phase completed; detail phase will continue."
                        if crawl_phase == "full"
                        else "Listing phase completed.",
                    },
                )

            db.commit()
            logger.info(
                "Listing done: %d pages, %d IDs found, %d staged, %d skipped existing",
                page_count,
                len(seen_ids),
                listing_count,
                jobs_skipped_existing,
            )

            if crawl_phase == "listing":
                detail_targets = []

            total_details = detail_target_rows
            for idx, target in enumerate(detail_targets):
                if idx > 0 and idx % 20 == 0:
                    await _check_and_handle_waf_challenge(
                        page, headed=args.headed, crawl_job_id=cj_id, db=db
                    )

                crawl_runtime.mark_detail_running(
                    listing_id=target["listing_id"],
                    detail_crawl_job_id=cj_id,
                )
                listing_payload = dict(target.get("listing_payload") or {})
                job_id = str(
                    listing_payload.get("job_id")
                    or listing_payload.get("jobId")
                    or ((listing_payload.get("raw_data") or {}).get("jobId") if isinstance(listing_payload.get("raw_data"), dict) else "")
                    or target.get("source_job_id")
                    or ""
                ).strip()
                encrypted_job_id = str(
                    listing_payload.get("encrypted_job_id")
                    or listing_payload.get("encryptJobId")
                    or ((listing_payload.get("raw_data") or {}).get("encryptJobId") if isinstance(listing_payload.get("raw_data"), dict) else "")
                    or job_id
                    or ""
                ).strip()
                jid = str(target.get("source_job_id") or job_id or "").strip()
                logger.info(
                    build_scrape_log_event(
                        "SCRAPE_DETAIL_ITEM_START",
                        source="offertoday",
                        crawl_job_id=cj_id,
                        detail_index=idx + 1,
                        detail_total=total_details,
                        source_job_id=jid or None,
                        listing_id=target["listing_id"],
                    )
                )
                if not job_id or not encrypted_job_id:
                    crawl_runtime.mark_detail_failed(
                        listing_id=target["listing_id"],
                        detail_crawl_job_id=cj_id,
                        error_message="Missing OfferToday detail identifiers",
                    )
                    detail_fail += 1
                    logger.warning(
                        build_scrape_log_event(
                            "SCRAPE_DETAIL_ITEM_FAIL",
                            source="offertoday",
                            crawl_job_id=cj_id,
                            detail_index=idx + 1,
                            detail_total=total_details,
                            source_job_id=jid or None,
                            error="missing_offer_today_detail_identifiers",
                        )
                    )
                    continue

                detail_success = False
                detail_payload: dict[str, Any] | None = None
                for attempt in range(1, 4):
                    await pause_before_detail_request()
                    data = await _fetch_detail_json_with_identifiers(
                        runtime,
                        job_id=job_id,
                        encrypted_job_id=encrypted_job_id,
                    )
                    if data and data.get("code") == 0 and data.get("data", {}).get("jobId"):
                        detail_payload = dict(data["data"])
                        detail_success = True
                        break

                    if data and data.get("code") == -1000035:
                        logger.warning("IP block detected (code=-1000035) at detail index %d", idx + 1)
                        ip_blocked = True
                        break

                    if attempt < 3:
                        await pause_after_transient_detail_failure(attempt - 1)

                if ip_blocked:
                    if args.crawl_job_id:
                        crawl_runtime.write_progress_event(
                            crawl_job_id=cj_id,
                            emitted_by="offertoday-crawl",
                            event_type="crawl.ip_blocked",
                            payload={
                                "error_code": -1000035,
                                "message": "IP has been blocked by OfferToday. Detail phase cannot continue.",
                                "detail_index": idx + 1,
                                "detail_total": total_details,
                                "detail_completed": detail_ok,
                                "detail_failed": detail_fail,
                            },
                        )
                        logger.warning(
                            build_scrape_log_event(
                                "SCRAPE_DETAIL_ITEM_IP_BLOCKED",
                                source="offertoday",
                                crawl_job_id=cj_id,
                                detail_index=idx + 1,
                                detail_total=total_details,
                                source_job_id=jid or None,
                                error_code=-1000035,
                            )
                        )
                        for remaining_target in detail_targets[idx:]:
                            crawl_runtime.mark_detail_failed(
                                listing_id=remaining_target["listing_id"],
                                detail_crawl_job_id=cj_id,
                                error_message="OfferToday IP blocked during detail phase",
                            )
                            detail_fail += 1
                    break

                if detail_success:
                    if detail_payload is None:
                        raise RuntimeError("OfferToday detail fetch succeeded without payload")
                    detail_ok += 1
                else:
                    crawl_runtime.mark_detail_failed(
                        listing_id=target["listing_id"],
                        detail_crawl_job_id=cj_id,
                        error_message="OfferToday detail fetch failed",
                    )
                    detail_fail += 1

                merged = {**listing_payload, **(detail_payload or {})}
                try:
                    canonical = build_offertoday_canonical_job(merged)
                    company_data = build_offertoday_company_data(canonical)
                    company, _company_action = company_repository.upsert_company(
                        db,
                        company_data,
                        auto_commit=False,
                    )
                    existing_job = job_repository.get_job_by_source_key(
                        db,
                        source_site="offertoday",
                        source_job_id=jid,
                    )
                    job_data = build_offertoday_job_data(canonical, company.id)
                    if existing_job is not None:
                        if not job_data.get("description") and existing_job.description:
                            job_data["description"] = existing_job.description
                        if not job_data.get("posted_date") and existing_job.posted_date:
                            job_data["posted_date"] = existing_job.posted_date

                    saved_job, _job_action = job_repository.upsert_source_job(
                        db,
                        job_data,
                        skip_existing=False,
                        auto_commit=False,
                    )
                    db.commit()
                    if detail_success:
                        crawl_runtime.mark_detail_completed(
                            listing_id=target["listing_id"],
                            detail_crawl_job_id=cj_id,
                            detail_payload=detail_payload or {},
                            published_job_id=saved_job.id,
                        )
                        logger.info(
                            build_scrape_log_event(
                                "SCRAPE_DETAIL_ITEM_OK",
                                source="offertoday",
                                crawl_job_id=cj_id,
                                detail_index=idx + 1,
                                detail_total=total_details,
                                source_job_id=jid or None,
                                published_job_id=saved_job.id,
                            )
                        )
                except Exception:
                    db.rollback()
                    logger.exception("Failed to persist OfferToday job source_job_id=%s", jid)
                    crawl_runtime.mark_detail_failed(
                        listing_id=target["listing_id"],
                        detail_crawl_job_id=cj_id,
                        error_message=f"Failed to persist OfferToday job source_job_id={jid}",
                    )
                    if detail_success:
                        detail_ok -= 1
                        detail_fail += 1
                    logger.warning(
                        build_scrape_log_event(
                            "SCRAPE_DETAIL_ITEM_FAIL",
                            source="offertoday",
                            crawl_job_id=cj_id,
                            detail_index=idx + 1,
                            detail_total=total_details,
                            source_job_id=jid or None,
                            error=f"persist_failed:{jid}",
                        )
                    )

                if (idx + 1) % 10 == 0:
                    if args.crawl_job_id:
                        crawl_runtime.write_progress_event(
                            crawl_job_id=cj_id,
                            emitted_by="offertoday-crawl",
                            event_type="crawl.detail_progress",
                            payload={
                                "detail_ok": detail_ok,
                                "detail_fail": detail_fail,
                                "detail_total": total_details,
                                "detail_index": idx + 1,
                                "detail_selected_rows": detail_selected_rows,
                                "detail_skipped_existing_rows": detail_skipped_existing_rows,
                                "detail_target_rows": total_details,
                                "phase": 2,
                            },
                        )
                        cj = db.query(CrawlJob).filter(CrawlJob.id == cj_id).first()
                        if cj:
                            cj.metrics = {
                                "pages_processed": page_count,
                                "job_ids_collected": len(seen_ids),
                                "listings_staged": listing_count,
                                "jobs_skipped_existing": jobs_skipped_existing,
                                "detail_selected_rows": detail_selected_rows,
                                "detail_skipped_existing_rows": detail_skipped_existing_rows,
                                "detail_target_rows": total_details,
                                "detail_pending": total_details - detail_ok - detail_fail,
                                "detail_completed": detail_ok,
                                "detail_failed": detail_fail,
                                "items_emitted": detail_ok,
                                "jobs_saved": detail_ok,
                            }
                        db.commit()

                await asyncio.sleep(1.5)

            db.commit()

        if args.crawl_job_id:
            crawl_runtime.mark_completed(
                crawl_job_id=cj_id,
                source_site="offertoday",
                payload={
                    "pages": page_count,
                    "listings": listing_count,
                    "detail_ok": detail_ok,
                    "detail_fail": detail_fail,
                    "ip_blocked": ip_blocked,
                },
                metrics={
                    "pages_processed": page_count,
                    "job_ids_collected": len(seen_ids),
                    "listings_staged": listing_count,
                    "new_jobs_added": new_jobs_count,
                    "jobs_skipped_existing": jobs_skipped_existing,
                    "detail_selected_rows": detail_selected_rows,
                    "detail_skipped_existing_rows": detail_skipped_existing_rows,
                    "detail_target_rows": total_details,
                    "detail_pending": max(total_details - detail_ok - detail_fail, 0),
                    "detail_completed": detail_ok,
                    "detail_failed": detail_fail,
                    "items_emitted": detail_ok,
                    "jobs_saved": detail_ok,
                    "search_families": search_families,
                },
                error_message="No new OfferToday jobs were discovered for this crawl."
                if new_jobs_count == 0 and crawl_phase != "detail"
                else None,
            )
            logger.info(
                build_scrape_log_event(
                    "SCRAPE_EXECUTOR_DONE",
                    source="offertoday",
                    crawl_job_id=cj_id,
                    crawl_phase=crawl_phase,
                    crawl_mode="headed" if args.headed else "headless",
                    job_ids_collected=len(seen_ids),
                    listings_staged=listing_count,
                    detail_target_rows=total_details,
                    detail_completed=detail_ok,
                    detail_failed=detail_fail,
                    jobs_skipped_existing=jobs_skipped_existing,
                )
            )
            logger.info("Crawl job %s: completed", cj_id)

    except Exception as exc:
        logger.error("Crawl failed: %s", exc)
        if args.crawl_job_id:
            crawl_runtime.mark_failed(
                crawl_job_id=cj_id,
                source_site="offertoday",
                error_message=str(exc),
                payload={"phase": 2 if crawl_phase == "detail" else 1},
            )
    finally:
        db.close()

    logger.info("Crawl done: pages=%d listings=%d ok=%d fail=%d", page_count, listing_count, detail_ok, detail_fail)


if __name__ == "__main__":
    asyncio.run(main())
