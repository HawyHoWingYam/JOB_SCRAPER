#!/usr/bin/env python3
"""Standalone OfferToday crawler with live progress events.

This path remains wired into the current crawl-job API. The crawl space is
expanded through OfferToday's IT category tree so the backend can collect a
broader set of IT job IDs instead of stopping at a narrow keyword probe.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("offertoday-crawl")

BACKEND = str(Path(__file__).resolve().parents[1])
SCRAPY_PROJECT = str(Path(__file__).resolve().parents[1] / "scrapy_project")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
if SCRAPY_PROJECT not in sys.path:
    sys.path.insert(0, SCRAPY_PROJECT)

from app.sources.offertoday.constants import OFFERTODAY_BASE_URL, OFFERTODAY_COMMON_HEADERS, OFFERTODAY_LISTING_BROWSE_URL, OFFERTODAY_LISTING_SEARCH_URL, build_offertoday_listing_payload  # noqa: E402
from app.sources.offertoday.search_space import (  # noqa: E402
    build_offertoday_listing_queries,
    normalize_offertoday_keywords,
)
from app.sources.offertoday.staging import resolve_listing_stage_decision  # noqa: E402
from app.sources.offertoday.parsers import parse_offertoday_listing_response  # noqa: E402
from job_scraper_spiders.downloaders.scrapling_adapter import scrapling_fetch  # noqa: E402

OFFERTODAY_DETAIL_URL_TPL = f"{OFFERTODAY_BASE_URL}/wapi/geek/recommend/jobDetail?id={{}}&encryptJobId={{}}"

MAX_PAGES_GLOBAL = 9999
DEFAULT_IT_UNIQUE_JOB_TARGET = 3000

# WAF challenge URL fragment — OfferToday redirects here when it detects unusual traffic.
_WAF_CHALLENGE_PATH = "/web/passport/cm/verify"
# How long to wait (seconds) for the user to complete manual WAF verification before giving up.
_WAF_MANUAL_TIMEOUT_SECONDS = 180

_COMMON_HEADERS = OFFERTODAY_COMMON_HEADERS


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


async def _fetch_listing_json(
    page, payload: dict[str, Any], *, listing_url: str | None = None
) -> dict[str, Any]:
    url = listing_url or OFFERTODAY_LISTING_SEARCH_URL
    js = (
        f"()=>fetch('{url}',{{method:'POST',"
        f"headers:{json.dumps(_COMMON_HEADERS, ensure_ascii=False)},"
        f"body:JSON.stringify({json.dumps(payload, ensure_ascii=False)})"
        f"}}).then(r=>r.json())"
    )
    try:
        return await asyncio.wait_for(page.evaluate(js), timeout=30)
    except Exception as exc:
        logger.warning("Playwright listing fetch failed; trying Scrapling fallback: %s", exc)

    try:
        text = await scrapling_fetch(
            url,
            method="POST",
            headers=_COMMON_HEADERS,
            data=json.dumps(payload, ensure_ascii=False),
            headless=True,
            stealth=True,
        )
        return json.loads(text) if text else {}
    except Exception as exc:
        logger.warning("Scrapling listing fallback failed: %s", exc)
        return {}


async def _fetch_detail_json(page, jid: str) -> dict[str, Any]:
    detail_url = OFFERTODAY_DETAIL_URL_TPL.format(jid, jid)
    js = (
        f"()=>fetch('{detail_url}',{{headers:{{"
        f"'api-language':'zh_HK','x-requested-with':'XMLHttpRequest'}}}}).then(r=>r.json())"
    )
    try:
        return await asyncio.wait_for(page.evaluate(js), timeout=30)
    except Exception as exc:
        logger.warning("Playwright detail fetch failed; trying Scrapling fallback: %s", exc)

    try:
        text = await scrapling_fetch(
            detail_url,
            method="GET",
            headers={
                "api-language": "zh_HK",
                "x-requested-with": "XMLHttpRequest",
            },
            headless=True,
            stealth=True,
        )
        return json.loads(text) if text else {}
    except Exception as exc:
        logger.warning("Scrapling detail fallback failed: %s", exc)
        return {}


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


def _emit_listing_completed_checkpoint(
    db,
    *,
    crawl_job_id: str,
    sequence_no: int,
    payload: dict[str, Any],
) -> None:
    """Write the checkpoint that marks the listing phase as finished."""
    _write_progress_event(
        db,
        crawl_job_id=crawl_job_id,
        sequence_no=sequence_no,
        event_type="listing_completed",
        payload=payload,
    )
    db.commit()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone OfferToday crawler")
    parser.add_argument("--category-ids", type=str, default="")
    parser.add_argument("--keywords", type=str, default="")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--crawl-job-id", type=str, default="")
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
        "--skip-existing",
        action="store_true",
        default=False,
        help="Do not queue detail work for jobs that already exist in the database.",
    )
    args = parser.parse_args()

    category_ids = [int(c.strip()) for c in args.category_ids.split(",") if c.strip().isdigit()]
    keywords = normalize_offertoday_keywords(args.keywords)
    page_limit_per_query = min(args.max_pages, MAX_PAGES_GLOBAL)
    listing_tasks = build_offertoday_listing_queries(
        category_ids,
        keywords=keywords or None,
        max_pages_per_query=page_limit_per_query,
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
    from app.models.crawl_job import CrawlJob, CrawlJobEvent
    from app.models.crawl_job_listing import CrawlJobListing
    from app.models.company import Company
    from app.models.job import Job
    from app.sources.contracts import build_offertoday_canonical_job
    from playwright.async_api import async_playwright

    db = SessionLocal()
    detail_ok = 0
    detail_fail = 0

    if args.crawl_job_id:
        cj_id = args.crawl_job_id
        cj = db.query(CrawlJob).filter(CrawlJob.id == cj_id).first()
        if cj:
            cj.status = "running"
            cj.started_at = datetime.now(timezone.utc)
            cj.metrics = {
                "pages_processed": 0,
                "job_ids_collected": 0,
                "listings_staged": 0,
                "detail_pending": 0,
                "items_emitted": 0,
                "jobs_saved": 0,
                "search_families": search_families,
            }
            db.flush()
            last_seq = db.query(CrawlJobEvent).filter(CrawlJobEvent.crawl_job_id == cj_id).count()
            _write_progress_event(
                db,
                crawl_job_id=cj_id,
                sequence_no=last_seq + 1,
                event_type="crawl.started",
                payload={"phase": 1, "source_site": "offertoday"},
            )
            db.commit()
            logger.info("Crawl job %s: running", cj_id)
    else:
        cj_id = str(uuid.uuid4())

    company = db.query(Company).filter(Company.source_site == "offertoday").first()
    if not company:
        company = Company(
            id=uuid.uuid4(),
            company_id="offertoday-default",
            source_site="offertoday",
            source_company_id="offertoday",
            name="OfferToday",
        )
        db.add(company)
        db.flush()
    company_id = company.id

    seen_ids: set[str] = set()
    listing_count = 0
    new_jobs_count = 0
    jobs_skipped_existing = 0
    page_count = 0
    search_family = ""
    event_seq = db.query(CrawlJobEvent).filter(CrawlJobEvent.crawl_job_id == cj_id).count() if args.crawl_job_id else 0

    existing_count = db.query(Job).filter(Job.source_site == "offertoday").count()
    logger.info("Existing OfferToday jobs in DB: %d", existing_count)
    logger.info(
        "OfferToday search space: tasks=%d families=%s max_pages_per_query=%d",
        len(listing_tasks),
        ", ".join(search_families) or "[none]",
        page_limit_per_query,
    )

    try:
        async with async_playwright() as pw:
            launch_args = [] if args.headed else ["--no-sandbox", "--disable-dev-shm-usage"]
            browser = await pw.chromium.launch(headless=not args.headed, args=launch_args)
            auth_state_path = Path(args.auth_state).resolve() if args.auth_state else None
            context_kwargs: dict = {
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
                ),
                "locale": "zh-HK",
            }
            if auth_state_path and auth_state_path.exists():
                context_kwargs["storage_state"] = str(auth_state_path)
                logger.info("Loading auth state from %s", auth_state_path)
            elif args.auth_state:
                logger.warning(
                    "Auth state file not found: %s — starting without pre-loaded session",
                    auth_state_path,
                )
            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()

            await page.goto(f"{OFFERTODAY_BASE_URL}/hk/search", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2.0)
            # Check immediately whether WAF fired on the warmup page.
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

                payload = build_offertoday_listing_payload(category_id=category_id, keyword=keyword, page=page_number)
                task_listing_url = (
                    OFFERTODAY_LISTING_BROWSE_URL
                    if task.get("endpoint") == "browse"
                    else None
                )
                data: dict[str, Any] = await _fetch_listing_json(page, payload, listing_url=task_listing_url)

                if not data or data.get("code") != 0:
                    consecutive_failures += 1
                    # After 3 consecutive bad responses, check for WAF challenge.
                    if consecutive_failures >= 3:
                        await _check_and_handle_waf_challenge(
                            page, headed=args.headed, crawl_job_id=cj_id, db=db
                        )
                        consecutive_failures = 0
                    continue

                consecutive_failures = 0

                # Periodic WAF check every 50 processed tasks.
                if task_index > 0 and task_index % 50 == 0:
                    await _check_and_handle_waf_challenge(
                        page, headed=args.headed, crawl_job_id=cj_id, db=db
                    )

                result_list = data.get("data", {}).get("resultList", [])
                if not result_list:
                    exhausted_conditions.add(condition_key)
                    continue

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

                    db.add(
                        CrawlJobListing(
                            id=uuid.uuid4(),
                            crawl_job_id=cj_id,
                            source_site="offertoday",
                            source_job_id=job_id_str,
                            source_url=f"{OFFERTODAY_BASE_URL}/hk/job/{job_id_str}",
                            listing_payload=enriched_listing,
                            detail_status="pending",
                        )
                    )
                    listing_count += 1

                page_count += 1

                if args.crawl_job_id:
                    event_seq += 1
                    _write_progress_event(
                        db,
                        crawl_job_id=cj_id,
                        sequence_no=event_seq,
                        event_type="crawl.page_processed",
                        payload={
                            "search_family": search_family,
                            "search_families": search_families,
                            "category_id": category_id,
                            "keyword": keyword,
                            "current_page": page_count,
                            "total_pages": planned_total_pages,
                            "job_ids_collected": len(seen_ids),
                            "listings_staged": listing_count,
                            "jobs_skipped_existing": jobs_skipped_existing,
                            "phase": 1,
                        },
                    )
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

            if args.crawl_job_id:
                event_seq += 1
                _emit_listing_completed_checkpoint(
                    db,
                    crawl_job_id=cj_id,
                    sequence_no=event_seq,
                    payload={
                        "phase": 1,
                        "search_families": search_families,
                        "pages_processed": page_count,
                        "job_ids_collected": len(seen_ids),
                        "listings_staged": listing_count,
                        "jobs_skipped_existing": jobs_skipped_existing,
                        "detail_selected_rows": len(seen_ids),
                        "detail_skipped_existing_rows": jobs_skipped_existing,
                        "detail_target_rows": listing_count,
                        "detail_pending": listing_count,
                        "message": "Listing phase completed; detail phase will continue.",
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

            listings = (
                db.query(CrawlJobListing)
                .filter(
                    CrawlJobListing.crawl_job_id == cj_id,
                    CrawlJobListing.detail_status == "pending",
                )
                .all()
            )
            total_details = len(listings)
            ip_blocked = False

            for idx, listing in enumerate(listings):
                # periodic WAF check — mirrors the listing-loop pattern
                if idx > 0 and idx % 20 == 0:
                    await _check_and_handle_waf_challenge(
                        page, headed=args.headed, crawl_job_id=cj_id, db=db
                    )

                jid = listing.source_job_id or ""
                if not jid:
                    continue

                detail_success = False
                for attempt in range(1, 4):
                    data = await _fetch_detail_json(page, jid)
                    if data and data.get("code") == 0 and data.get("data", {}).get("jobId"):
                        listing.detail_payload = dict(data["data"])
                        listing.detail_status = "completed"
                        detail_success = True
                        break

                    # IP block detection: code -1000035 = IP 行为异常, an environment-level block
                    if data and data.get("code") == -1000035:
                        logger.warning("IP block detected (code=-1000035) at detail index %d", idx + 1)
                        ip_blocked = True
                        break

                    if attempt < 3:
                        await asyncio.sleep(2.0 ** attempt)

                if ip_blocked:
                    # Environment-level block — write event, bulk-fail remaining, break
                    if args.crawl_job_id:
                        event_seq += 1
                        _write_progress_event(
                            db,
                            crawl_job_id=cj_id,
                            sequence_no=event_seq,
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
                        # bulk mark remaining pending as failed
                        remaining = total_details - detail_ok - detail_fail
                        if remaining > 0:
                            db.query(CrawlJobListing).filter(
                                CrawlJobListing.crawl_job_id == cj_id,
                                CrawlJobListing.detail_status == "pending",
                            ).update({"detail_status": "failed"}, synchronize_session=False)
                            detail_fail += remaining
                        db.commit()
                    break

                if detail_success:
                    detail_ok += 1
                else:
                    listing.detail_status = "failed"
                    detail_fail += 1

                merged = {**(listing.listing_payload or {}), **(listing.detail_payload or {})}
                try:
                    canonical = build_offertoday_canonical_job(merged)
                    exists = (
                        db.query(Job)
                        .filter(Job.source_site == "offertoday", Job.source_job_id == jid)
                        .first()
                    )
                    if not exists:
                        db.add(
                            Job(
                                id=uuid.uuid4(),
                                job_id=jid,
                                source_site="offertoday",
                                source_job_id=jid,
                                company_id=company_id,
                                title=canonical.title or "",
                                description=canonical.description or "",
                                location=canonical.location or "",
                                salary_range=canonical.salary_range or "",
                                employment_type=canonical.employment_type or "",
                                raw_data=canonical.raw_data,
                                created_at=datetime.utcnow(),
                                updated_at=datetime.utcnow(),
                                is_deleted=False,
                            )
                        )
                except Exception:
                    pass

                if (idx + 1) % 10 == 0:
                    if args.crawl_job_id:
                        event_seq += 1
                        _write_progress_event(
                            db,
                            crawl_job_id=cj_id,
                            sequence_no=event_seq,
                            event_type="crawl.detail_progress",
                            payload={
                                "detail_ok": detail_ok,
                                "detail_fail": detail_fail,
                                "detail_total": total_details,
                                "detail_index": idx + 1,
                                "detail_selected_rows": len(seen_ids),
                                "detail_skipped_existing_rows": jobs_skipped_existing,
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
                                "detail_selected_rows": len(seen_ids),
                                "detail_skipped_existing_rows": jobs_skipped_existing,
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
            await browser.close()

        if args.crawl_job_id:
            event_seq += 1
            _write_progress_event(
                db,
                crawl_job_id=cj_id,
                sequence_no=event_seq,
                event_type="crawl.completed",
                payload={
                    "pages": page_count,
                    "listings": listing_count,
                    "detail_ok": detail_ok,
                    "detail_fail": detail_fail,
                    "ip_blocked": ip_blocked,
                },
            )
            cj = db.query(CrawlJob).filter(CrawlJob.id == cj_id).first()
            if cj:
                cj.status = "completed"
                cj.completed_at = datetime.now(timezone.utc)
                cj.metrics = {
                    "pages_processed": page_count,
                    "job_ids_collected": len(seen_ids),
                    "listings_staged": listing_count,
                    "new_jobs_added": new_jobs_count,
                    "jobs_skipped_existing": jobs_skipped_existing,
                    "detail_selected_rows": len(seen_ids),
                    "detail_skipped_existing_rows": jobs_skipped_existing,
                    "detail_target_rows": listing_count,
                    "detail_pending": 0,
                    "detail_completed": detail_ok,
                    "detail_failed": detail_fail,
                    "items_emitted": detail_ok,
                    "jobs_saved": detail_ok,
                    "search_families": search_families,
                }
                if new_jobs_count == 0:
                    cj.error_message = "No new OfferToday jobs were discovered for this crawl."
                db.commit()
                logger.info("Crawl job %s: completed", cj_id)

    except Exception as exc:
        logger.error("Crawl failed: %s", exc)
        if args.crawl_job_id:
            cj = db.query(CrawlJob).filter(CrawlJob.id == cj_id).first()
            if cj:
                cj.status = "failed"
                cj.error_message = str(exc)
                cj.completed_at = datetime.now(timezone.utc)
                db.commit()
    finally:
        db.close()

    logger.info("Crawl done: pages=%d listings=%d ok=%d fail=%d", page_count, listing_count, detail_ok, detail_fail)


if __name__ == "__main__":
    asyncio.run(main())
