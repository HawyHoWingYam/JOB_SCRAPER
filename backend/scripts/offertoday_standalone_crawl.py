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

from app.sources.offertoday.search_space import (  # noqa: E402
    build_offertoday_listing_queries,
    normalize_offertoday_keywords,
)
from job_scraper_spiders.downloaders.scrapling_adapter import scrapling_fetch  # noqa: E402

OFFERTODAY_BASE_URL = "https://www.offertoday.com"
OFFERTODAY_LISTING_URL = "https://www.offertoday.com/wapi/geek/recommend/search/list"
OFFERTODAY_DETAIL_URL_TPL = "https://www.offertoday.com/wapi/geek/recommend/jobDetail?id=%s&encryptJobId=%s"

MAX_PAGES_GLOBAL = 9999
DEFAULT_IT_UNIQUE_JOB_TARGET = 3000

_COMMON_HEADERS = {
    "api-language": "zh_HK",
    "x-requested-with": "XMLHttpRequest",
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json;charset=UTF-8",
}


def _build_listing_payload(*, category_id: int | None, keyword: str, page: int) -> dict[str, Any]:
    payload = {
        "keyword": keyword,
        "rcdType": 7,
        "pageSize": 10,
        "page": page,
        "salaryType": 0,
        "employmentTypes": [],
        "publishTime": "",
        "experiences": [],
        "educationLevels": [],
        "benefits": [],
        "industries": [],
        "subDistrictCodes": [],
        "needShowDistance": False,
        "searchSource": None,
    }
    if category_id is not None:
        payload["jobFunctionCodes"] = [category_id]
    return payload


async def _fetch_listing_json(page, payload: dict[str, Any]) -> dict[str, Any]:
    js = (
        f"()=>fetch('{OFFERTODAY_LISTING_URL}',{{method:'POST',"
        f"headers:{json.dumps(_COMMON_HEADERS, ensure_ascii=False)},"
        f"body:JSON.stringify({json.dumps(payload, ensure_ascii=False)})"
        f"}}).then(r=>r.json())"
    )
    try:
        return await page.evaluate(js)
    except Exception as exc:
        logger.warning("Playwright listing fetch failed; trying Scrapling fallback: %s", exc)

    try:
        text = await scrapling_fetch(
            OFFERTODAY_LISTING_URL,
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
    detail_url = OFFERTODAY_DETAIL_URL_TPL % (jid, jid)
    js = (
        f"()=>fetch('{detail_url}',{{headers:{{"
        f"'api-language':'zh_HK','x-requested-with':'XMLHttpRequest'}}}}).then(r=>r.json())"
    )
    try:
        return await page.evaluate(js)
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


async def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone OfferToday crawler")
    parser.add_argument("--category-ids", type=str, default="")
    parser.add_argument("--keywords", type=str, default="")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--crawl-job-id", type=str, default="")
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
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="zh-HK",
            )
            page = await context.new_page()

            await page.goto(f"{OFFERTODAY_BASE_URL}/hk/search", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2.0)
            logger.info("Warmup complete")

            exhausted_conditions: set[tuple[str, Any, Any]] = set()
            for task in listing_tasks:
                search_family = str(task.get("search_family") or "").strip() or "category_search"
                category_id = task.get("category_id")
                keyword = str(task.get("keyword") or "")
                page_number = int(task.get("page") or 1)
                condition_key = (search_family, category_id, keyword)
                if condition_key in exhausted_conditions:
                    continue

                payload = _build_listing_payload(category_id=category_id, keyword=keyword, page=page_number)
                data: dict[str, Any] = await _fetch_listing_json(page, payload)

                if not data or data.get("code") != 0:
                    continue

                result_list = data.get("data", {}).get("resultList", [])
                if not result_list:
                    exhausted_conditions.add(condition_key)
                    continue

                for raw_job in result_list:
                    job_id_str = str(raw_job.get("jobId") or "").strip()
                    if not job_id_str or job_id_str in seen_ids:
                        continue
                    seen_ids.add(job_id_str)

                    from app.sources.offertoday.parsers import parse_offertoday_listing_response

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
                    if not already_in_db:
                        new_jobs_count += 1

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

                    if not already_in_db:
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
                                "detail_pending": listing_count,
                                "items_emitted": 0,
                                "jobs_saved": 0,
                                "search_families": search_families,
                                "search_family": search_family,
                            }
                    db.commit()

                await asyncio.sleep(0.5)

                if default_it_crawl and len(seen_ids) >= DEFAULT_IT_UNIQUE_JOB_TARGET:
                    logger.info(
                        "Default IT crawl reached unique target (%d); stopping listing phase.",
                        DEFAULT_IT_UNIQUE_JOB_TARGET,
                    )
                    break

                if not data.get("data", {}).get("hasMore"):
                    exhausted_conditions.add(condition_key)
            if default_it_crawl and len(seen_ids) >= DEFAULT_IT_UNIQUE_JOB_TARGET:
                logger.info("Default IT crawl target reached; skipping remaining listing tasks.")

            db.commit()
            logger.info("Listing done: %d pages, %d unique IDs", page_count, listing_count)

            listings = (
                db.query(CrawlJobListing)
                .filter(
                    CrawlJobListing.crawl_job_id == cj_id,
                    CrawlJobListing.detail_status == "pending",
                )
                .all()
            )
            total_details = len(listings)

            for idx, listing in enumerate(listings):
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

                    if attempt < 3:
                        await asyncio.sleep(2.0 ** attempt)

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
                                "phase": 2,
                            },
                        )
                        cj = db.query(CrawlJob).filter(CrawlJob.id == cj_id).first()
                        if cj:
                            cj.metrics = {
                                "pages_processed": page_count,
                                "job_ids_collected": len(seen_ids),
                                "listings_staged": listing_count,
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
