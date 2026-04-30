"""CTgoodjobs Scrape Service (Orchestrator).

Keeps the existing JobsDB CategoryScrapeService intact and provides a parallel
service for CTgoodjobs production scraper modules.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

import app.database as database
from app.scraper.ctgoodjobs.category_registry import CTGOODJOBS_BASE_URL, CTGoodJobsCategory
from app.scraper.ctgoodjobs.detail_scraper import fetch_detail_page_html, parse_detail_page
from app.scraper.ctgoodjobs.list_scraper import (
    category_page_url,
    fetch_category_page_html,
    parse_category_page,
)
from app.scraper.ctgoodjobs.merge import merge_ctgoodjobs_job
from app.scraper.ctgoodjobs.category_registry import parse_category_registry
from app.services.database_service import DatabaseService
from app.services.enrichment_run_service import EnrichmentRunService
from app.services.progress_store import get_progress_store
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


async def _fetch_ctgoodjobs_registry_html(*, timeout_s: float = 30.0) -> str:
    url = f"{CTGOODJOBS_BASE_URL}/jobs"
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def _namespaced_job_id(raw_job_id: str) -> str:
    raw = raw_job_id.strip()
    if raw.startswith("ctgoodjobs:"):
        return raw
    return f"ctgoodjobs:{raw}"


def _detail_url_for_job(raw_job_id: str) -> str:
    # Best-effort stable detail URL. Tests typically stub fetch/parse anyway.
    return f"{CTGOODJOBS_BASE_URL}/job/{raw_job_id.strip()}"


class CtgoodjobsScrapeService:
    """Orchestrates category-based scraping for CTgoodjobs."""

    def __init__(self, db_session=None, redis_client=None):
        self.db = db_session
        self.redis = redis_client
        self._progress_store = get_progress_store()

    def get_progress(self, category_key: str) -> Optional[Dict]:
        return self._progress_store.get(category_key)

    def get_all_progress(self) -> Dict[Any, Dict]:
        return self._progress_store.get_all()

    def _calculate_rates(self, category_key: str) -> Dict[str, Any]:
        progress = self._progress_store.get(category_key)
        if not progress:
            return {}

        def _parse(ts: Optional[str]) -> Optional[datetime]:
            if not ts:
                return None
            try:
                return datetime.fromisoformat(ts)
            except ValueError:
                return None

        started_at = _parse(progress.get("started_at"))
        phase_started_at = _parse(progress.get("phase_started_at")) or started_at
        if started_at is None or phase_started_at is None:
            return {}

        now = utc_now()
        elapsed = (now - started_at).total_seconds()
        phase_elapsed = (now - phase_started_at).total_seconds()

        jobs_scraped = int(progress.get("jobs_scraped", 0) or 0)
        overall_rate = jobs_scraped / elapsed if elapsed > 0 else 0
        phase_rate = jobs_scraped / phase_elapsed if phase_elapsed > 0 else 0

        return {
            "elapsed_seconds": int(elapsed),
            "phase_elapsed_seconds": int(phase_elapsed),
            "overall_rate": round(overall_rate, 2),
            "phase_rate": round(phase_rate, 2),
        }

    def _record_failure(
        self,
        category_key: str,
        *,
        failure_type: str,
        message: str,
        **context: Any,
    ) -> None:
        progress = self._progress_store.get(category_key) or {}
        errors = list(progress.get("errors") or [])
        failure = {"type": failure_type, "message": message}
        failure.update(context)
        errors.append(failure)

        update: dict[str, Any] = {"errors": errors}
        if failure_type == "page":
            update["page_failures"] = int(progress.get("page_failures", 0) or 0) + 1
        elif failure_type == "detail":
            update["detail_failures"] = int(progress.get("detail_failures", 0) or 0) + 1

        self._progress_store.update(category_key, update)

    async def _load_registry_categories(self) -> list[CTGoodJobsCategory]:
        html = await _fetch_ctgoodjobs_registry_html()
        return parse_category_registry(html)

    async def _scrape_category_details(
        self,
        *,
        category: CTGoodJobsCategory,
        max_pages: int,
        skip_existing: bool,
        batch_size: int,
    ) -> list[dict[str, Any]]:
        category_key = category.source_classification_id

        self._progress_store.update(
            category_key,
            {
                "status": "collecting_ids",
                "source_site": "ctgoodjobs",
                "category_name": category.name,
                "mapping_status": category.mapping_status,
                "phase": 1,
                "job_ids_collected": 0,
                "jobs_scraped": 0,
                "page_failures": 0,
                "detail_failures": 0,
                "errors": [],
                "started_at": utc_now().isoformat(),
                "phase_started_at": utc_now().isoformat(),
            },
        )

        raw_job_ids: list[str] = []
        job_url_by_id: dict[str, str] = {}
        seen: set[str] = set()

        for page in range(1, max_pages + 1):
            url = category_page_url(category.url, page=page)
            try:
                page_html = await fetch_category_page_html(url)
                parsed = parse_category_page(
                    page_html,
                    category_slug=category.slug,
                    source_classification_id=category.source_classification_id,
                    source_classification_name=category.name,
                    page=page,
                    url=url,
                )
            except Exception as exc:
                logger.warning(
                    "Skipping CTgoodjobs category page after failure: category=%s page=%s url=%s error=%s",
                    category_key,
                    page,
                    url,
                    exc,
                )
                self._record_failure(
                    category_key,
                    failure_type="page",
                    message=str(exc),
                    page=page,
                    url=url,
                )
                continue

            page_job_ids = parsed.get("job_ids") or []
            page_job_urls = parsed.get("job_urls") or []

            for job_url in page_job_urls:
                if not isinstance(job_url, str) or not job_url.strip():
                    continue
                # Best-effort: parse_category_page already extracted IDs from URLs; in tests
                # we usually provide 1:1 ordering between job_ids and job_urls.
            for idx, raw_id in enumerate(page_job_ids):
                if not isinstance(raw_id, str) or not raw_id.strip() or raw_id in seen:
                    continue
                seen.add(raw_id)
                raw_job_ids.append(raw_id)
                if idx < len(page_job_urls) and isinstance(page_job_urls[idx], str):
                    job_url_by_id[raw_id] = page_job_urls[idx]

            self._progress_store.update(
                category_key,
                {
                    "current_page": page,
                    "total_pages": max_pages,
                    "job_ids_collected": len(raw_job_ids),
                    **self._calculate_rates(category_key),
                },
            )

        if skip_existing and raw_job_ids:
            db_service = DatabaseService()
            namespaced = [_namespaced_job_id(rid) for rid in raw_job_ids]
            db = database.SessionLocal()
            try:
                new_ids, _existing_ids = db_service.filter_existing_job_ids(db, namespaced)
            finally:
                db.close()

            allowed = set(new_ids)
            raw_job_ids = [rid for rid in raw_job_ids if _namespaced_job_id(rid) in allowed]

        self._progress_store.update(
            category_key,
            {
                "status": "scraping_details",
                "phase": 2,
                "total_jobs": len(raw_job_ids),
                "phase_started_at": utc_now().isoformat(),
            },
        )

        merged_jobs: list[dict[str, Any]] = []
        category_dict = category.to_dict()

        for i in range(0, len(raw_job_ids), batch_size):
            batch = raw_job_ids[i : i + batch_size]
            for raw_id in batch:
                detail_url = job_url_by_id.get(raw_id) or _detail_url_for_job(raw_id)
                try:
                    page_html = await fetch_detail_page_html(detail_url)
                    detail = parse_detail_page(
                        page_html,
                        source_classification_id=category.source_classification_id,
                        source_classification_name=category.name,
                        source_classification_slug=category.slug,
                        url=detail_url,
                    )
                    list_job = {
                        "source_site": "ctgoodjobs",
                        "job_id": raw_id,
                        "url": detail_url,
                        "source_classification_id": category.source_classification_id,
                        "source_classification_name": category.name,
                    }
                    merged = merge_ctgoodjobs_job(
                        category=category_dict,
                        list_job=list_job,
                        detail_job=detail,
                    )
                except Exception as exc:
                    logger.warning(
                        "Skipping CTgoodjobs job after detail failure: category=%s job_id=%s url=%s error=%s",
                        category_key,
                        raw_id,
                        detail_url,
                        exc,
                    )
                    self._record_failure(
                        category_key,
                        failure_type="detail",
                        message=str(exc),
                        job_id=raw_id,
                        url=detail_url,
                    )
                    continue

                merged_jobs.append(merged)

                self._progress_store.update(
                    category_key,
                    {
                        "jobs_scraped": len(merged_jobs),
                        "current_job_id": raw_id,
                        "current_job_title": merged.get("title"),
                        **self._calculate_rates(category_key),
                    },
                )

        return merged_jobs

    async def scrape_categories(
        self,
        *,
        category_ids: list[str],
        max_pages: int = 3,
        skip_existing: bool = True,
        batch_size: int = 25,
    ) -> Dict[str, Any]:
        """Scrape one or more CTgoodjobs top-level categories and persist results."""

        db_service = DatabaseService()
        total_stats: Dict[str, Any] = {
            "jobs_created": 0,
            "jobs_updated": 0,
            "jobs_skipped": 0,
            "failed": 0,
            "categories_processed": 0,
            "affected_job_ids": [],
        }

        registry_categories = await self._load_registry_categories()
        registry_by_key = {c.source_classification_id: c for c in registry_categories}

        for category_key in category_ids:
            category = registry_by_key.get(category_key)
            if category is None:
                logger.warning("CTgoodjobs category not found in registry: %s", category_key)
                continue

            try:
                details = await self._scrape_category_details(
                    category=category,
                    max_pages=max_pages,
                    skip_existing=skip_existing,
                    batch_size=batch_size,
                )

                progress = self._progress_store.get(category.source_classification_id) or {}
                page_failures = int(progress.get("page_failures", 0) or 0)
                detail_failures = int(progress.get("detail_failures", 0) or 0)
                if not details and (page_failures > 0 or detail_failures > 0):
                    # Distinguish legitimate empty categories from failure-driven zero output.
                    self._progress_store.update(
                        category.source_classification_id,
                        {
                            "status": "failed",
                            "error": "no_usable_jobs_produced_after_failures",
                        },
                    )
                    total_stats["failed"] += 1
                    continue

                if details:
                    details = db_service.deduplicate_jobs(details)

                    self._progress_store.update(
                        category.source_classification_id,
                        {
                            "status": "saving_to_db",
                            "phase": 4,
                            "jobs_saved": 0,
                            "save_total": len(details),
                            "phase_started_at": utc_now().isoformat(),
                        },
                    )

                    db = database.SessionLocal()
                    try:
                        def on_save_progress(saved_count: int) -> None:
                            self._progress_store.update(
                                category.source_classification_id,
                                {
                                    "jobs_saved": saved_count,
                                    **self._calculate_rates(category.source_classification_id),
                                },
                            )

                        stats = await db_service.save_scraped_jobs(
                            details,
                            db,
                            skip_existing=skip_existing,
                            on_progress=on_save_progress,
                        )

                        affected_job_ids = stats.get("affected_job_ids") or []
                        if category.mapping_status == "clean_match":
                            EnrichmentRunService(db).create_post_scrape_run_for_batch(affected_job_ids)

                        db.commit()

                        total_stats["affected_job_ids"].extend(affected_job_ids)
                        total_stats["jobs_created"] += stats.get("jobs_created", 0)
                        total_stats["jobs_updated"] += stats.get("jobs_updated", 0)
                        total_stats["jobs_skipped"] += stats.get("jobs_skipped", 0)
                        total_stats["failed"] += stats.get("failed", 0)
                    except Exception:
                        db.rollback()
                        raise
                    finally:
                        db.close()

                self._progress_store.update(
                    category.source_classification_id,
                    {
                        "status": "completed",
                        "completed_at": utc_now().isoformat(),
                    },
                )
                total_stats["categories_processed"] += 1
            except Exception as e:
                logger.exception("Error scraping CTgoodjobs category %s", category_key)
                self._progress_store.update(
                    category.source_classification_id,
                    {"status": "failed", "error": str(e)},
                )
                total_stats["failed"] += 1

        return total_stats
