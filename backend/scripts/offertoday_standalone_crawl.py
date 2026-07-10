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
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("offertoday-crawl")

BACKEND = str(Path(__file__).resolve().parents[1])
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.sources.offertoday.constants import (  # noqa: E402
    build_offertoday_listing_payload,
)
from app.scraper.manual_action import (  # noqa: E402
    ManualActionRequiredError,
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
)
from app.config import settings  # noqa: E402
from app.scraper.log_events import build_scrape_log_event  # noqa: E402
from app.services.crawl_job_runtime import CrawlJobRuntime  # noqa: E402
from app.services.offertoday_detail_pipeline import (  # noqa: E402
    OfferTodayDetailPipeline,
    OfferTodayDetailTarget,
)
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime  # noqa: E402
from app.repositories.crawl_job_repository import CrawlJobRepository  # noqa: E402
from app.sources.offertoday.listing_runner import (  # noqa: E402
    ListingRetryPolicy,
    ListingStopPolicy,
    OfferTodayListingRunner,
    listing_observation_to_payload,
)
from app.sources.offertoday.search_space import (  # noqa: E402
    build_offertoday_listing_conditions,
    normalize_offertoday_keywords,
)
from app.sources.offertoday.parsers import (  # noqa: E402
    build_offertoday_job_url,
)
from app.sources.offertoday.response_policy import (  # noqa: E402
    OfferTodayResponseKind,
)

MAX_PAGES_GLOBAL = 9999
DEFAULT_IT_UNIQUE_JOB_TARGET = 5000

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


def _build_runtime_request_payload(
    args,
    *,
    crawl_phase: str,
    source_listing_crawl_job_id: str | None,
) -> dict[str, Any]:
    category_ids = _normalize_listing_category_ids(args.category_ids)
    detail_statuses = _normalize_detail_statuses(args.detail_statuses)
    payload: dict[str, Any] = {
        "crawl_phase": crawl_phase,
        "crawl_mode": "headed" if args.headed else "headless",
        "category_ids": category_ids,
        "max_pages": int(args.max_pages),
        "detail_limit": int(args.detail_limit),
        "detail_statuses": detail_statuses,
        "skip_existing": bool(args.skip_existing),
        "resume_strategy": str(args.resume_strategy or RESUME_STRATEGY_FRESH_PROFILE),
    }
    keywords = normalize_offertoday_keywords(args.keywords)
    if keywords:
        payload["keywords"] = ",".join(keywords)
    if source_listing_crawl_job_id:
        payload["source_listing_crawl_job_id"] = source_listing_crawl_job_id
    return payload


def _build_manual_action_payload(
    args,
    exc: ManualActionRequiredError,
    *,
    crawl_phase: str,
    source_listing_crawl_job_id: str | None,
) -> dict[str, Any]:
    payload = exc.to_payload(
        crawl_mode="headed" if args.headed else "headless",
        browser_channel=settings.offertoday_headed_browser_channel,
        browser_profile_path=settings.offertoday_headed_browser_user_data_dir,
    )
    resume_context: dict[str, Any] = {
        "crawl_phase": crawl_phase,
        "crawl_mode": "headed" if args.headed else "headless",
        "category_ids": _normalize_listing_category_ids(args.category_ids),
        "skip_existing": bool(args.skip_existing),
        "resume_strategy": str(args.resume_strategy or RESUME_STRATEGY_FRESH_PROFILE),
    }
    keywords = normalize_offertoday_keywords(args.keywords)
    if keywords:
        resume_context["keywords"] = ",".join(keywords)
    if crawl_phase == "listing":
        resume_context["max_pages"] = int(args.max_pages)
    else:
        resume_context["detail_limit"] = int(args.detail_limit)
        resume_context["detail_statuses"] = _normalize_detail_statuses(
            args.detail_statuses
        )
        if source_listing_crawl_job_id:
            resume_context["source_listing_crawl_job_id"] = source_listing_crawl_job_id

    payload["resume_context"] = {
        **resume_context,
        **dict(payload.get("resume_context") or {}),
    }
    return payload


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


def _normalize_listing_category_ids(value: Any) -> list[int]:
    raw_values = str(value or "").split(",") if isinstance(value, str) else value or []
    normalized: list[int] = []
    for raw_value in raw_values:
        text = str(raw_value).strip()
        if text.isdigit():
            normalized.append(int(text))
    return normalized


def _normalize_detail_statuses(value: Any) -> list[str]:
    raw_values = str(value or "").split(",") if isinstance(value, str) else value or []
    return [str(raw_value).strip() for raw_value in raw_values if str(raw_value).strip()]


def _build_listing_staging_payload(
    parsed_row: dict[str, Any],
    *,
    condition,
    page: int,
    rank: int,
) -> dict[str, Any]:
    normalized_listing = dict(parsed_row or {})
    job_id = str(normalized_listing.get("job_id") or "").strip()
    encrypted_job_id = str(
        normalized_listing.get("encrypted_job_id") or ""
    ).strip()
    if not job_id:
        raise ValueError("OfferToday listing row is missing canonical job_id")
    if not encrypted_job_id:
        raise ValueError("OfferToday listing row is missing encrypted_job_id")

    raw_data = normalized_listing.get("raw_data")
    normalized_listing["raw_data"] = (
        dict(raw_data) if isinstance(raw_data, dict) else {}
    )
    category_id = getattr(condition, "category_id", None)
    search_family = str(getattr(condition, "search_family", "") or "").strip()
    keyword = str(getattr(condition, "keyword", "") or "")
    return {
        "source_job_id": job_id,
        "source_url": build_offertoday_job_url(encrypted_job_id),
        "source_classification_id": (
            str(category_id) if category_id is not None else None
        ),
        "source_classification_name": search_family or None,
        "listing_page": int(page),
        "listing_rank": int(rank),
        "listing_payload": normalized_listing,
        "search_family": search_family or None,
        "category_id": str(category_id) if category_id is not None else None,
        "category_name": search_family or None,
        "keyword": keyword or None,
        "page": int(page),
    }


class OfferTodayCrawlStagingSink:
    def __init__(self, *, crawl_runtime, crawl_job_id, skip_existing: bool) -> None:
        self.crawl_runtime = crawl_runtime
        self.crawl_job_id = crawl_job_id
        self.skip_existing = bool(skip_existing)
        self.rows_staged = 0
        self.rows_created = 0
        self.skipped_existing = 0
        self.created_source_job_ids: list[str] = []
        self.preexisting_staged_source_job_ids: list[str] = []
        self.published_source_job_ids: list[str] = []

    async def stage_page(self, *, condition, page: int, rows) -> None:
        payloads = [
            _build_listing_staging_payload(
                parsed_row,
                condition=condition,
                page=page,
                rank=index,
            )
            for index, parsed_row in enumerate(rows, start=1)
        ]
        result = self.crawl_runtime.stage_listing_batch(
            crawl_job_id=self.crawl_job_id,
            source_site="offertoday",
            payloads=payloads,
            skip_existing=self.skip_existing,
        )
        self.rows_staged += int(result.rows_staged)
        self.rows_created += int(result.rows_created)
        self.skipped_existing += int(result.skipped_existing)
        self.created_source_job_ids.extend(result.created_source_job_ids)
        self.preexisting_staged_source_job_ids.extend(
            result.preexisting_staged_source_job_ids
        )
        self.published_source_job_ids.extend(result.published_source_job_ids)

    async def defer_identity_conflict(
        self,
        *,
        job_ids,
        encrypted_job_ids,
        reason: str,
    ) -> None:
        self.crawl_runtime.defer_listing_identity_conflict(
            crawl_job_id=self.crawl_job_id,
            source_job_ids=tuple(job_ids),
            encrypted_job_ids=tuple(encrypted_job_ids),
            reason=reason,
        )


class CrawlJobListingObservationSink:
    def __init__(self, *, crawl_runtime, crawl_job_id) -> None:
        self.crawl_runtime = crawl_runtime
        self.crawl_job_id = crawl_job_id

    async def record_page_attempt(self, observation) -> None:
        self.crawl_runtime.write_progress_event(
            crawl_job_id=self.crawl_job_id,
            emitted_by="offertoday-crawl",
            event_type="crawl.listing_page_attempt",
            payload=listing_observation_to_payload(observation),
        )

    async def record_condition_outcome(self, outcome) -> None:
        suffix = "completed" if outcome.is_complete else "incomplete"
        self.crawl_runtime.write_progress_event(
            crawl_job_id=self.crawl_job_id,
            emitted_by="offertoday-crawl",
            event_type=f"crawl.listing_condition_{suffix}",
            payload=listing_observation_to_payload(outcome),
        )


class MemoryListingObservationSink:
    def __init__(self) -> None:
        self.page_attempts: list[Any] = []
        self.condition_outcomes: list[Any] = []

    async def record_page_attempt(self, observation) -> None:
        self.page_attempts.append(observation)

    async def record_condition_outcome(self, outcome) -> None:
        self.condition_outcomes.append(outcome)


class NoopListingStagingSink:
    def __init__(self) -> None:
        self.deferred_conflicts: list[dict[str, Any]] = []

    async def stage_page(self, *, condition, page: int, rows) -> None:
        return None

    async def defer_identity_conflict(
        self,
        *,
        job_ids,
        encrypted_job_ids,
        reason: str,
    ) -> None:
        self.deferred_conflicts.append(
            {
                "job_ids": tuple(job_ids),
                "encrypted_job_ids": tuple(encrypted_job_ids),
                "reason": reason,
            }
        )


@dataclass(frozen=True)
class ProductionListingPhaseResult:
    listing_result: Any
    staging_sink: OfferTodayCrawlStagingSink
    observation_sink: CrawlJobListingObservationSink
    detail_load_result: Any | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.listing_result, name)

    @property
    def detail_targets(self) -> list[dict[str, Any]]:
        if self.detail_load_result is None:
            return []
        return list(self.detail_load_result.targets)

    @property
    def rows_created(self) -> int:
        return self.staging_sink.rows_created


def _listing_result_evidence(result) -> dict[str, Any]:
    return {
        "stop_reason": str(result.stop_reason),
        "gap_count": len(result.gaps),
        "conflict_count": len(result.identity_conflicts),
        "identity_issue_count": len(result.identity_issues),
        "pages_observed": sum(
            int(getattr(outcome, "pages_observed", 0) or 0)
            for outcome in result.condition_outcomes
        ),
        "accepted_job_ids": list(result.accepted_job_ids),
    }


async def _run_listing_phase(
    args,
    browser_runtime,
    crawl_runtime,
    crawl_job_id,
    listing_runner=OfferTodayListingRunner,
) -> ProductionListingPhaseResult:
    category_ids = _normalize_listing_category_ids(args.category_ids)
    keywords = normalize_offertoday_keywords(args.keywords)
    conditions = build_offertoday_listing_conditions(
        category_ids,
        keywords=keywords or None,
        default_to_it=True,
    )
    is_default_it_crawl = not keywords and any(
        condition.search_family in {"it_category", "it_keyword", "it_hybrid"}
        for condition in conditions
    )
    observation_sink = CrawlJobListingObservationSink(
        crawl_runtime=crawl_runtime,
        crawl_job_id=crawl_job_id,
    )
    staging_sink = OfferTodayCrawlStagingSink(
        crawl_runtime=crawl_runtime,
        crawl_job_id=crawl_job_id,
        skip_existing=bool(args.skip_existing),
    )
    runner = (
        listing_runner(browser_runtime)
        if isinstance(listing_runner, type)
        else listing_runner
    )

    await browser_runtime.require_healthy_session()
    result = await runner.run(
        conditions=conditions,
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=min(int(args.max_pages), MAX_PAGES_GLOBAL),
            unique_job_cap=(
                DEFAULT_IT_UNIQUE_JOB_TARGET if is_default_it_crawl else None
            ),
            require_empty_confirmation=True,
        ),
        retry_policy=ListingRetryPolicy(
            max_attempts_per_page=3,
            retry_delays_seconds=(1.0, 2.0),
            page_delay_seconds=1.5,
        ),
        observation_sink=observation_sink,
        staging_sink=staging_sink,
        session_mode="headed" if args.headed else "headless",
    )
    execution = ProductionListingPhaseResult(
        listing_result=result,
        staging_sink=staging_sink,
        observation_sink=observation_sink,
    )
    evidence = _listing_result_evidence(result)
    if not result.is_complete:
        stop_reason = str(result.stop_reason)
        manual_session_reasons = {"auth_expired", "waf_challenge", "ip_blocked"}
        identity_reasons = {"identity_issue", "identity_conflict", "id_mismatch"}
        if stop_reason in manual_session_reasons | identity_reasons:
            action_type = (
                "identity_audit"
                if stop_reason in identity_reasons
                else "session_recovery"
            )
            manual_payload = {
                "action_type": action_type,
                "classification": stop_reason,
                "evidence": evidence,
                "resume_context": {
                    "crawl_phase": "listing",
                    "crawl_mode": "headed" if args.headed else "headless",
                    "category_ids": category_ids,
                    "keywords": keywords,
                    "max_pages": int(args.max_pages),
                    "skip_existing": bool(args.skip_existing),
                    "resume_strategy": str(args.resume_strategy),
                },
            }
            crawl_runtime.mark_manual_action_required(
                crawl_job_id=crawl_job_id,
                source_site="offertoday",
                request_payload=dict(manual_payload["resume_context"]),
                payload=manual_payload,
                error_message=(
                    "OfferToday listing phase requires manual action: "
                    f"{stop_reason}"
                ),
            )
        else:
            crawl_runtime.mark_failed(
                crawl_job_id=crawl_job_id,
                source_site="offertoday",
                error_message=f"OfferToday listing phase incomplete: {stop_reason}",
                payload=evidence,
            )
        return execution

    if str(args.crawl_phase or "").strip().lower() == "full":
        accepted_source_job_ids = list(result.accepted_job_ids)
        detail_load_result = crawl_runtime.load_detail_targets(
            source_site="offertoday",
            request_payload={
                "crawl_phase": "detail",
                "crawl_mode": "headed" if args.headed else "headless",
                "category_ids": category_ids,
                "source_job_ids": accepted_source_job_ids,
                "detail_limit": len(accepted_source_job_ids),
                "detail_statuses": _normalize_detail_statuses(
                    args.detail_statuses
                ),
                "skip_existing": bool(args.skip_existing),
            },
            detail_crawl_job_id=crawl_job_id,
        )
        execution = ProductionListingPhaseResult(
            listing_result=result,
            staging_sink=staging_sink,
            observation_sink=observation_sink,
            detail_load_result=detail_load_result,
        )
    return execution


@dataclass(frozen=True, slots=True)
class OfferTodayDetailPhaseResult:
    detail_load_result: Any
    processed_targets: int
    outcome_counts: dict[str, int]
    jobs_created: int
    jobs_updated: int
    jobs_reconciled: int
    companies_created: int
    companies_updated: int
    terminal_unavailable: int
    persist_failure: int
    stop_batch: bool

    @property
    def jobs_saved(self) -> int:
        return self.jobs_created + self.jobs_updated


async def _run_detail_phase(
    *,
    args,
    browser_runtime,
    crawl_runtime: CrawlJobRuntime,
    crawl_job_id,
    detail_load_result=None,
    pipeline=None,
    completion_payload: dict[str, Any] | None = None,
    completion_metrics: dict[str, Any] | None = None,
) -> OfferTodayDetailPhaseResult:
    crawl_phase = str(args.crawl_phase or "").strip().lower()
    source_listing_crawl_job_id, detail_scope = _resolve_detail_scope(
        args,
        listing_phase_completed=crawl_phase == "full",
    )
    request_payload = _build_runtime_request_payload(
        args,
        crawl_phase="detail",
        source_listing_crawl_job_id=source_listing_crawl_job_id,
    )

    if crawl_phase == "detail":
        await browser_runtime.require_healthy_session()
    if detail_load_result is None:
        detail_load_result = crawl_runtime.load_detail_targets(
            source_site="offertoday",
            request_payload=request_payload,
            detail_crawl_job_id=crawl_job_id,
        )

    cohort_payload = {
        "fetch_cohort_source_job_ids": list(
            detail_load_result.fetch_cohort_source_job_ids
        ),
        "fetch_cohort_hash": str(detail_load_result.fetch_cohort_hash),
        "reconciled_source_job_ids": list(
            detail_load_result.reconciled_source_job_ids
        ),
        "identity_conflict_ids": list(detail_load_result.identity_conflict_ids),
        "identity_conflict_evidence": [
            dict(evidence)
            for evidence in detail_load_result.identity_conflict_evidence
        ],
        "fetch_cohort_distinct": len(
            detail_load_result.fetch_cohort_source_job_ids
        ),
    }
    crawl_runtime.write_progress_event(
        crawl_job_id=crawl_job_id,
        emitted_by="offertoday-crawl",
        event_type="crawl.detail_cohort_frozen",
        payload=cohort_payload,
    )
    logger.info(
        build_scrape_log_event(
            "SCRAPE_DETAIL_TARGETS_LOADED",
            source="offertoday",
            crawl_job_id=crawl_job_id,
            source_listing_crawl_job_id=source_listing_crawl_job_id,
            detail_scope=detail_scope,
            detail_selected_rows=detail_load_result.selected_rows,
            detail_skipped_existing_rows=detail_load_result.skipped_existing_rows,
            detail_target_rows=detail_load_result.target_rows,
            fetch_cohort_hash=detail_load_result.fetch_cohort_hash,
        )
    )

    jobs_reconciled = len(detail_load_result.reconciled_source_job_ids)
    outcome_counts: dict[str, int] = {}
    jobs_created = 0
    jobs_updated = 0
    companies_created = 0
    companies_updated = 0

    def build_metrics_patch() -> dict[str, Any]:
        jobs_saved = jobs_created + jobs_updated
        return {
            "jobs_created": jobs_created,
            "jobs_updated": jobs_updated,
            "jobs_reconciled": jobs_reconciled,
            "companies_created": companies_created,
            "companies_updated": companies_updated,
            "terminal_unavailable": int(
                outcome_counts.get(
                    OfferTodayResponseKind.TERMINAL_UNAVAILABLE.value,
                    0,
                )
            ),
            "persist_failure": int(
                outcome_counts.get(
                    OfferTodayResponseKind.PERSIST_FAILURE.value,
                    0,
                )
            ),
            "items_emitted": jobs_saved,
            "jobs_saved": jobs_saved,
            "detail_processed_targets": sum(outcome_counts.values()),
            "detail_outcomes": dict(outcome_counts),
        }

    def build_result(*, stop_batch: bool) -> OfferTodayDetailPhaseResult:
        return OfferTodayDetailPhaseResult(
            detail_load_result=detail_load_result,
            processed_targets=sum(outcome_counts.values()),
            outcome_counts=dict(outcome_counts),
            jobs_created=jobs_created,
            jobs_updated=jobs_updated,
            jobs_reconciled=jobs_reconciled,
            companies_created=companies_created,
            companies_updated=companies_updated,
            terminal_unavailable=int(
                outcome_counts.get(
                    OfferTodayResponseKind.TERMINAL_UNAVAILABLE.value,
                    0,
                )
            ),
            persist_failure=int(
                outcome_counts.get(OfferTodayResponseKind.PERSIST_FAILURE.value, 0)
            ),
            stop_batch=stop_batch,
        )

    if detail_load_result.identity_conflict_ids:
        evidence = {
            "identity_conflict_ids": list(
                detail_load_result.identity_conflict_ids
            ),
            "identity_conflict_evidence": [
                dict(record)
                for record in detail_load_result.identity_conflict_evidence
            ],
        }
        crawl_runtime.merge_metrics(
            crawl_job_id=crawl_job_id,
            metrics_patch=build_metrics_patch(),
        )
        crawl_runtime.mark_manual_action_required(
            crawl_job_id=crawl_job_id,
            source_site="offertoday",
            request_payload=request_payload,
            payload={
                "action_type": "identity_audit",
                "classification": "identity_conflict",
                "evidence": evidence,
                "resume_context": request_payload,
            },
            error_message="OfferToday detail identity audit is required",
        )
        return build_result(stop_batch=True)

    async def fetch_detail(*, job_id: str, encrypted_job_id: str):
        return await _fetch_detail_json_with_identifiers(
            browser_runtime,
            job_id=job_id,
            encrypted_job_id=encrypted_job_id,
        )

    if pipeline is None:
        from app.database import SessionLocal
        from app.repositories.company_repository import CompanyRepository
        from app.repositories.job_repository import JobRepository

        pipeline = OfferTodayDetailPipeline(
            session_factory=SessionLocal,
            crawl_runtime=crawl_runtime,
            company_repository=CompanyRepository(),
            job_repository=JobRepository(),
            sleep=asyncio.sleep,
            clock=time.monotonic,
            max_attempts=3,
            retry_delays_seconds=(1.0, 2.0),
        )

    total_targets = int(detail_load_result.target_rows)
    for index, runtime_target in enumerate(detail_load_result.targets, start=1):
        target = OfferTodayDetailTarget.from_runtime_target(runtime_target)
        result = await pipeline.process_target(
            target=target,
            detail_crawl_job_id=crawl_job_id,
            fetch_detail=fetch_detail,
        )
        outcome_key = result.outcome.value
        outcome_counts[outcome_key] = outcome_counts.get(outcome_key, 0) + 1
        if result.job_action == "created":
            jobs_created += 1
        elif result.job_action == "updated":
            jobs_updated += 1
        if result.company_action == "created":
            companies_created += 1
        elif result.company_action == "updated":
            companies_updated += 1

        if result.stop_batch:
            identity_stop = result.outcome is OfferTodayResponseKind.ID_MISMATCH
            manual_payload = {
                "action_type": (
                    "identity_audit" if identity_stop else "session_recovery"
                ),
                "classification": result.outcome.value,
                "evidence": {
                    "source_job_id": target.identity.job_id,
                    "listing_ids": [
                        str(listing_id) for listing_id in target.listing_ids
                    ],
                    "detail_index": index,
                    "detail_total": total_targets,
                },
                "resume_context": request_payload,
            }
            crawl_runtime.merge_metrics(
                crawl_job_id=crawl_job_id,
                metrics_patch=build_metrics_patch(),
            )
            crawl_runtime.mark_manual_action_required(
                crawl_job_id=crawl_job_id,
                source_site="offertoday",
                request_payload=request_payload,
                payload=manual_payload,
                error_message=(
                    "OfferToday detail phase requires manual action: "
                    f"{result.outcome.value}"
                ),
            )
            return build_result(stop_batch=True)

        if index % 10 == 0:
            checkpoint_metrics = build_metrics_patch()
            crawl_runtime.merge_metrics(
                crawl_job_id=crawl_job_id,
                metrics_patch=checkpoint_metrics,
            )
            crawl_runtime.write_progress_event(
                crawl_job_id=crawl_job_id,
                emitted_by="offertoday-crawl",
                event_type="crawl.detail_progress",
                payload={
                    "detail_index": index,
                    "detail_total": total_targets,
                    "outcome_counts": checkpoint_metrics["detail_outcomes"],
                    "jobs_created": checkpoint_metrics["jobs_created"],
                    "jobs_updated": checkpoint_metrics["jobs_updated"],
                    "jobs_reconciled": checkpoint_metrics["jobs_reconciled"],
                    "phase": 2,
                },
            )

    phase_result = build_result(stop_batch=False)
    completed_payload = {
        **dict(completion_payload or {}),
        "detail_outcomes": dict(phase_result.outcome_counts),
        "jobs_created": phase_result.jobs_created,
        "jobs_updated": phase_result.jobs_updated,
        "jobs_reconciled": phase_result.jobs_reconciled,
        "terminal_unavailable": phase_result.terminal_unavailable,
        "persist_failure": phase_result.persist_failure,
    }
    completed_metrics = {
        **dict(completion_metrics or {}),
        **build_metrics_patch(),
    }
    crawl_runtime.mark_completed(
        crawl_job_id=crawl_job_id,
        source_site="offertoday",
        payload=completed_payload,
        metrics=completed_metrics,
    )
    return phase_result


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
    listing_conditions = (
        build_offertoday_listing_conditions(
            category_ids,
            keywords=keywords or None,
            default_to_it=True,
        )
        if crawl_phase != "detail"
        else []
    )
    search_families = list(
        dict.fromkeys(
            condition.search_family
            for condition in listing_conditions
            if str(condition.search_family or "").strip()
        )
    )
    source_listing_crawl_job_id, detail_scope = _resolve_detail_scope(
        args,
        listing_phase_completed=False,
    )

    from app.database import SessionLocal
    from app.models.crawl_job import CrawlJob
    from app.models.job import Job

    db = SessionLocal()
    crawl_runtime = CrawlJobRuntime()
    detail_ok = 0
    detail_fail = 0
    detail_phase_result: OfferTodayDetailPhaseResult | None = None

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

    existing_count = db.query(Job).filter(Job.source_site == "offertoday").count()
    logger.info("Existing OfferToday jobs in DB: %d", existing_count)
    logger.info(
        "OfferToday search space: tasks=%d families=%s max_pages_per_query=%d",
        len(listing_conditions),
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

            listing_execution: ProductionListingPhaseResult | None = None
            if crawl_phase != "detail":
                listing_execution = await _run_listing_phase(
                    args=args,
                    browser_runtime=runtime,
                    crawl_runtime=crawl_runtime,
                    crawl_job_id=cj_id,
                )
                listing_result = listing_execution.listing_result
                seen_ids.update(listing_result.ordered_job_ids)
                listing_count = int(listing_execution.rows_created)
                new_jobs_count = int(listing_execution.rows_created)
                jobs_skipped_existing = int(
                    listing_execution.staging_sink.skipped_existing
                )
                page_count = sum(
                    int(outcome.pages_observed or 0)
                    for outcome in listing_result.condition_outcomes
                )
                if not listing_result.is_complete:
                    logger.warning(
                        "Listing phase incomplete; stop_reason=%s pages=%d",
                        listing_result.stop_reason,
                        page_count,
                    )
                    return

            detail_load_result = (
                listing_execution.detail_load_result
                if (
                    crawl_phase == "full"
                    and listing_execution is not None
                    and listing_execution.detail_load_result is not None
                )
                else None
            )
            detail_target_rows = int(
                getattr(detail_load_result, "target_rows", 0) or 0
            )
            detail_selected_rows = int(
                getattr(detail_load_result, "selected_rows", 0) or 0
            )
            detail_skipped_existing_rows = int(
                getattr(detail_load_result, "skipped_existing_rows", 0) or 0
            )

            if args.crawl_job_id and crawl_phase != "detail":
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

            total_details = detail_target_rows
            if crawl_phase in {"full", "detail"}:
                detail_phase_result = await _run_detail_phase(
                    args=args,
                    browser_runtime=runtime,
                    crawl_runtime=crawl_runtime,
                    crawl_job_id=cj_id,
                    detail_load_result=detail_load_result,
                    completion_payload={
                        "pages": page_count,
                        "listings": listing_count,
                    },
                    completion_metrics={
                        "pages_processed": page_count,
                        "job_ids_collected": len(seen_ids),
                        "listings_staged": listing_count,
                        "new_jobs_added": new_jobs_count,
                        "jobs_skipped_existing": jobs_skipped_existing,
                        "search_families": search_families,
                    },
                )
                total_details = int(
                    detail_phase_result.detail_load_result.target_rows
                )
                detail_ok = int(
                    detail_phase_result.outcome_counts.get(
                        OfferTodayResponseKind.SUCCESS.value,
                        0,
                    )
                )
                detail_fail = max(
                    detail_phase_result.processed_targets
                    - detail_ok
                    - detail_phase_result.terminal_unavailable,
                    0,
                )
                if detail_phase_result.stop_batch:
                    return

        if args.crawl_job_id and crawl_phase == "listing":
            crawl_runtime.mark_completed(
                crawl_job_id=cj_id,
                source_site="offertoday",
                payload={
                    "pages": page_count,
                    "listings": listing_count,
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
                    "detail_pending": 0,
                    "items_emitted": 0,
                    "jobs_saved": 0,
                    "search_families": search_families,
                },
                error_message=(
                    "No new OfferToday jobs were discovered for this crawl."
                    if new_jobs_count == 0
                    else None
                ),
            )

        if args.crawl_job_id:
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
                    jobs_created=(
                        detail_phase_result.jobs_created
                        if detail_phase_result is not None
                        else 0
                    ),
                    jobs_updated=(
                        detail_phase_result.jobs_updated
                        if detail_phase_result is not None
                        else 0
                    ),
                    jobs_reconciled=(
                        detail_phase_result.jobs_reconciled
                        if detail_phase_result is not None
                        else 0
                    ),
                    terminal_unavailable=(
                        detail_phase_result.terminal_unavailable
                        if detail_phase_result is not None
                        else 0
                    ),
                    persist_failure=(
                        detail_phase_result.persist_failure
                        if detail_phase_result is not None
                        else 0
                    ),
                    jobs_skipped_existing=jobs_skipped_existing,
                )
            )
            logger.info("Crawl job %s: completed", cj_id)

    except ManualActionRequiredError as exc:
        logger.warning("Crawl paused for manual action: %s", exc.message)
        if args.crawl_job_id:
            resume_crawl_phase = "detail" if crawl_phase == "detail" else "listing"
            resume_source_listing_crawl_job_id = source_listing_crawl_job_id
            if resume_crawl_phase == "listing":
                resume_source_listing_crawl_job_id = str(cj_id)
            crawl_runtime.mark_manual_action_required(
                crawl_job_id=cj_id,
                source_site="offertoday",
                request_payload=_build_runtime_request_payload(
                    args,
                    crawl_phase=resume_crawl_phase,
                    source_listing_crawl_job_id=resume_source_listing_crawl_job_id,
                ),
                payload=_build_manual_action_payload(
                    args,
                    exc,
                    crawl_phase=resume_crawl_phase,
                    source_listing_crawl_job_id=resume_source_listing_crawl_job_id,
                ),
                error_message=exc.message,
            )
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
