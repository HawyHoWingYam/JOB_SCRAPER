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
    RESUMABLE_SESSION_CLASSIFICATIONS,
    normalize_manual_action_payload,
)
from app.config import settings  # noqa: E402
from app.scraper.log_events import build_scrape_log_event  # noqa: E402
from app.services.crawl_job_runtime import (  # noqa: E402
    CrawlJobRuntime,
    OfferTodayListingIdentityConflictError,
)
from app.services.crawl_cancellation_token import (  # noqa: E402
    CrawlCancellationRequested,
    CrawlCancellationToken,
    resolve_cancellation_token,
)
from app.services.detail_pacing import build_detail_pacing_controller  # noqa: E402
from app.services.offertoday_listing_staging_service import (  # noqa: E402
    OfferTodayReconciledListingStagingSink,
    build_offertoday_listing_staging_payload,
)
from app.services.offertoday_detail_pipeline import (  # noqa: E402
    OfferTodayDetailPipeline,
    OfferTodayDetailTarget,
)
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime  # noqa: E402
from app.repositories.crawl_job_repository import CrawlJobRepository  # noqa: E402
from app.sources.offertoday.listing_runner import (  # noqa: E402
    ListingRetryPolicy,
    ListingStopPolicy,
    OfferTodayListingCondition,
    OfferTodayListingRunner,
    listing_observation_to_payload,
)
from app.sources.offertoday.listing_contract import (  # noqa: E402
    production_offertoday_listing_request_policy,
)
from app.sources.offertoday.search_space import (  # noqa: E402
    build_offertoday_listing_conditions,
    normalize_offertoday_keywords,
)
from app.source_catalog.runtime import load_published_query_plan  # noqa: E402
from app.sources.offertoday.response_policy import (  # noqa: E402
    OfferTodayResponseKind,
)

MAX_PAGES_GLOBAL = 9999
DEFAULT_MAX_PAGES_PER_CONDITION = 100

# WAF challenge URL fragment — OfferToday redirects here when it detects unusual traffic.
_WAF_CHALLENGE_PATH = "/web/passport/cm/verify"
# How long to wait (seconds) for the user to complete manual WAF verification before giving up.
_WAF_MANUAL_TIMEOUT_SECONDS = 180

_RESUME_STRATEGY_CHOICES = (
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
)
_IDENTITY_AUDIT_CLASSIFICATIONS = {
    "identity_issue",
    "identity_conflict",
    "id_mismatch",
}


async def _check_and_handle_waf_challenge(
    page,
    *,
    headed: bool,
    crawl_job_id: str,
    db: Any,
    cancellation_token=None,
) -> bool:
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
        if cancellation_token is None:
            await asyncio.sleep(1.5)
        else:
            await cancellation_token.sleep(1.5)
        return True
    except Exception as exc:
        logger.warning("WAF wait timed out or failed: %s", exc)

    return True


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone OfferToday crawler")
    parser.add_argument("--category-ids", type=str, default="")
    parser.add_argument("--keywords", type=str, default="")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES_PER_CONDITION,
    )
    parser.add_argument("--crawl-job-id", type=str, default="")
    parser.add_argument("--execution-generation", type=str, default="")
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
        rcd_type=None,
        page_size=10,
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
    if "source_listing_crawl_job_id" in request_payload:
        args.source_listing_crawl_job_id = str(
            request_payload.get("source_listing_crawl_job_id") or ""
        )
    requested_detail_scope = str(request_payload.get("detail_scope") or "").strip().lower()
    if requested_detail_scope:
        args.detail_scope = requested_detail_scope
    elif requested_phase == "detail":
        args.detail_scope = (
            "listing_batch"
            if str(getattr(args, "source_listing_crawl_job_id", "") or "").strip()
            else "global"
        )
    if request_payload.get("detail_limit") is not None:
        args.detail_limit = int(request_payload["detail_limit"])
    detail_statuses = request_payload.get("detail_statuses")
    if detail_statuses:
        args.detail_statuses = ",".join(str(status) for status in detail_statuses if str(status).strip())
    args.manual_action_browser_channel = str(
        request_payload.get("manual_action_browser_channel") or ""
    ).strip()
    args.manual_action_browser_profile_path = str(
        request_payload.get("manual_action_browser_profile_path") or ""
    ).strip()
    args.detail_pacing = request_payload.get("detail_pacing")


def _resolve_detail_scope(
    args,
    *,
    listing_phase_completed: bool,
) -> tuple[str | None, str]:
    requested_source_listing_crawl_job_id = str(args.source_listing_crawl_job_id or "").strip() or None
    requested_scope = str(getattr(args, "detail_scope", "") or "").strip().lower()
    if requested_scope and requested_scope not in {"global", "listing_batch"}:
        raise ValueError(f"Unsupported OfferToday detail scope: {requested_scope}")
    if not requested_scope:
        requested_scope = (
            "listing_batch"
            if requested_source_listing_crawl_job_id or listing_phase_completed
            else "global"
        )
    if requested_scope == "global":
        if requested_source_listing_crawl_job_id:
            raise ValueError(
                "OfferToday global detail scope cannot carry a listing batch ID"
            )
        return None, "global"
    resolved_batch_id = requested_source_listing_crawl_job_id
    if resolved_batch_id is None and listing_phase_completed:
        resolved_batch_id = str(args.crawl_job_id)
    if not resolved_batch_id:
        raise ValueError(
            "OfferToday listing_batch detail scope requires a listing batch ID"
        )
    return resolved_batch_id, "listing_batch"


def _build_runtime_request_payload(
    args,
    *,
    crawl_phase: str,
    source_listing_crawl_job_id: str | None,
    detail_scope: str | None = None,
) -> dict[str, Any]:
    category_ids = _parse_catalog_classification_ids(args.category_ids)
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
    if crawl_phase == "detail":
        resolved_scope = str(detail_scope or "").strip().lower() or (
            "listing_batch" if source_listing_crawl_job_id else "global"
        )
        if resolved_scope not in {"global", "listing_batch"}:
            raise ValueError(f"Unsupported OfferToday detail scope: {resolved_scope}")
        if resolved_scope == "global" and source_listing_crawl_job_id:
            raise ValueError(
                "OfferToday global detail scope cannot carry a listing batch ID"
            )
        if resolved_scope == "listing_batch" and not source_listing_crawl_job_id:
            raise ValueError(
                "OfferToday listing_batch detail scope requires a listing batch ID"
            )
        payload["detail_scope"] = resolved_scope
    if source_listing_crawl_job_id:
        payload["source_listing_crawl_job_id"] = source_listing_crawl_job_id
    if crawl_phase == "detail" and isinstance(
        getattr(args, "detail_pacing", None), dict
    ):
        payload["detail_pacing"] = dict(args.detail_pacing)
    return payload


def _build_manual_action_payload(
    args,
    exc: ManualActionRequiredError,
    *,
    crawl_phase: str,
    source_listing_crawl_job_id: str | None,
    detail_scope: str | None = None,
) -> dict[str, Any]:
    payload = exc.to_payload(
        crawl_mode="headed" if args.headed else "headless",
        browser_channel=settings.jobsdb_headed_browser_channel,
        browser_profile_path=settings.jobsdb_headed_browser_user_data_dir,
    )
    resume_context: dict[str, Any] = {
        "crawl_phase": crawl_phase,
        "crawl_mode": "headed" if args.headed else "headless",
        "category_ids": _parse_catalog_classification_ids(args.category_ids),
        "skip_existing": bool(args.skip_existing),
        "resume_strategy": str(args.resume_strategy or RESUME_STRATEGY_FRESH_PROFILE),
    }
    keywords = normalize_offertoday_keywords(args.keywords)
    if keywords:
        resume_context["keywords"] = ",".join(keywords)
    if crawl_phase == "listing":
        resume_context["max_pages"] = int(args.max_pages)
    else:
        resolved_scope = str(detail_scope or "").strip().lower() or (
            "listing_batch" if source_listing_crawl_job_id else "global"
        )
        resume_context["detail_scope"] = resolved_scope
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
    return normalize_manual_action_payload(
        payload,
        source_site="offertoday",
        request_payload=payload["resume_context"],
        default_browser_channel=settings.jobsdb_headed_browser_channel,
        default_browser_profile_path=settings.jobsdb_headed_browser_user_data_dir,
    )


def _build_result_manual_action_payload(
    *,
    crawl_phase: str,
    classification: str,
    evidence: dict[str, Any],
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    normalized_classification = str(classification or "").strip().lower()
    resume_supported = (
        normalized_classification in RESUMABLE_SESSION_CLASSIFICATIONS
    )
    identity_audit = normalized_classification in _IDENTITY_AUDIT_CLASSIFICATIONS
    action_type = (
        "session_recovery"
        if resume_supported
        else "identity_audit" if identity_audit else "operator_review"
    )
    payload: dict[str, Any] = {
        "action_type": action_type,
        "source_site": "offertoday",
        "stage": crawl_phase,
        "classification": normalized_classification,
        "code": evidence.get("code"),
        "blocked_url": evidence.get("blocked_url"),
        "evidence": dict(evidence),
        "resume_context": dict(request_payload),
        "resume_supported": resume_supported,
        "reuse_open_browser_supported": resume_supported,
    }
    if identity_audit:
        payload["message"] = (
            f"OfferToday {crawl_phase} identity evidence requires operator review; "
            "this crawl cannot be resumed automatically."
        )
        payload["instructions"] = [
            "Review the recorded OfferToday identity-conflict evidence.",
            "Start a corrected crawl only after resolving the identity mismatch.",
        ]
    elif not resume_supported:
        payload["message"] = (
            f"OfferToday {crawl_phase} stopped with {normalized_classification}; "
            "operator review is required and automatic resume is disabled."
        )
        payload["instructions"] = [
            "Review the recorded OfferToday stop evidence before starting another crawl.",
        ]

    return normalize_manual_action_payload(
        payload,
        source_site="offertoday",
        request_payload=request_payload,
        default_browser_channel=settings.jobsdb_headed_browser_channel,
        default_browser_profile_path=settings.jobsdb_headed_browser_user_data_dir,
    )


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


def _parse_catalog_classification_ids(value: Any) -> list[int | str]:
    raw_values = str(value or "").split(",") if isinstance(value, str) else value or []
    parsed: list[int | str] = []
    for raw_value in raw_values:
        text = str(raw_value).strip()
        if not text:
            continue
        if text.isdigit():
            parsed.append(int(text))
            continue
        prefix, separator, native_id = text.partition(":")
        if separator and prefix == "offertoday" and native_id.isdigit():
            parsed.append(text)
            continue
        raise ValueError(f"Invalid OfferToday Source Classification ID: {text}")
    return parsed


def _resolve_published_listing_category_ids(value: Any) -> list[int]:
    category_ids = _parse_catalog_classification_ids(value)
    if not category_ids:
        return []
    plan = load_published_query_plan("offertoday", category_ids)
    return [int(entry.target.payload["category_code"]) for entry in plan.entries]


def _build_request_listing_conditions(
    category_value: Any,
    *,
    keywords: list[str],
) -> list[OfferTodayListingCondition]:
    category_ids = _parse_catalog_classification_ids(category_value)
    if category_ids and keywords:
        plan = load_published_query_plan("offertoday", category_ids)
        validated_native_ids = [
            int(entry.target.payload["category_code"]) for entry in plan.entries
        ]
        return build_offertoday_listing_conditions(
            validated_native_ids,
            keywords=keywords,
            default_to_it=False,
            endpoint="search",
            category_endpoint="search",
            rcd_type=None,
        )
    if not category_ids:
        return build_offertoday_listing_conditions(
            [],
            keywords=keywords or None,
            default_to_it=True,
            endpoint="search",
            category_endpoint="search",
            rcd_type=None,
        )
    plan = load_published_query_plan("offertoday", category_ids)
    return [
        OfferTodayListingCondition(
            search_family="catalog_category",
            category_id=int(entry.target.payload["category_code"]),
            keyword=str(entry.target.payload["keyword"]),
            endpoint=str(entry.target.payload["endpoint"]),
            rcd_type=int(entry.target.payload["rcd_type"]),
        )
        for entry in plan.entries
    ]


def _normalize_detail_statuses(value: Any) -> list[str]:
    raw_values = str(value or "").split(",") if isinstance(value, str) else value or []
    return [str(raw_value).strip() for raw_value in raw_values if str(raw_value).strip()]


_build_listing_staging_payload = build_offertoday_listing_staging_payload


def _production_listing_observation_payload(observation) -> dict[str, Any]:
    payload = listing_observation_to_payload(observation)
    response_url = str(getattr(observation, "response_url", "") or "").strip()
    if response_url:
        payload["response_url"] = response_url
    for field_name in (
        "supplemental_identity_issues",
        "supplemental_identity_conflicts",
    ):
        values = getattr(observation, field_name, ())
        if values:
            payload[field_name] = listing_observation_to_payload(values)
    return payload


class CrawlJobListingObservationSink:
    def __init__(
        self,
        *,
        crawl_runtime,
        crawl_job_id,
        crawl_mode: str,
        cancellation_token=None,
    ) -> None:
        self.crawl_runtime = crawl_runtime
        self.crawl_job_id = crawl_job_id
        self.crawl_mode = crawl_mode
        self.cancellation_token = cancellation_token
        self._started_condition_ids: set[str] = set()
        self._success_latency_ms: dict[tuple[str, int], int] = {}
        self.page_attempt_count = 0
        self.successful_page_count = 0

    async def record_page_start(
        self,
        *,
        condition,
        page: int,
        attempt: int,
        max_attempts: int,
    ) -> None:
        if self.cancellation_token is not None:
            self.cancellation_token.raise_if_cancelled()
        if condition.condition_id not in self._started_condition_ids:
            self._started_condition_ids.add(condition.condition_id)
            logger.info(
                build_scrape_log_event(
                    "SCRAPE_LISTING_CATEGORY_START",
                    source="offertoday",
                    crawl_job_id=self.crawl_job_id,
                    crawl_phase="listing",
                    crawl_mode=self.crawl_mode,
                    condition_id=condition.condition_id,
                    search_family=condition.search_family,
                    category_id=condition.category_id,
                    keyword=condition.keyword or None,
                )
            )
        logger.info(
            build_scrape_log_event(
                "SCRAPE_LISTING_PAGE_START",
                source="offertoday",
                crawl_job_id=self.crawl_job_id,
                crawl_phase="listing",
                crawl_mode=self.crawl_mode,
                condition_id=condition.condition_id,
                search_family=condition.search_family,
                category_id=condition.category_id,
                keyword=condition.keyword or None,
                current_page=page,
                attempt=attempt,
                max_attempts=max_attempts,
            )
        )

    async def record_page_attempt(self, observation) -> None:
        self.page_attempt_count += 1
        if observation.classification == OfferTodayResponseKind.SUCCESS.value:
            self.successful_page_count += 1
            self._success_latency_ms[
                (observation.condition_id, observation.page)
            ] = int(observation.latency_ms)
            if observation.row_count == 0:
                logger.info(
                    build_scrape_log_event(
                        "SCRAPE_LISTING_BATCH_STAGED",
                        source="offertoday",
                        crawl_job_id=self.crawl_job_id,
                        crawl_phase="listing",
                        crawl_mode=self.crawl_mode,
                        condition_id=observation.condition_id,
                        search_family=observation.search_family,
                        category_id=observation.category_id,
                        keyword=observation.keyword or None,
                        current_page=observation.page,
                        attempt=observation.attempt,
                        elapsed_ms=observation.latency_ms,
                        job_ids=0,
                        listings_staged=0,
                        outcome="empty_page",
                    )
                )
        else:
            event_name = (
                "SCRAPE_LISTING_PAGE_RETRY"
                if observation.retry_reason
                else "SCRAPE_LISTING_MANUAL_ACTION"
                if observation.classification
                in RESUMABLE_SESSION_CLASSIFICATIONS
                else "SCRAPE_LISTING_PAGE_FAIL"
            )
            logger.warning(
                build_scrape_log_event(
                    event_name,
                    source="offertoday",
                    crawl_job_id=self.crawl_job_id,
                    crawl_phase="listing",
                    crawl_mode=self.crawl_mode,
                    condition_id=observation.condition_id,
                    search_family=observation.search_family,
                    category_id=observation.category_id,
                    keyword=observation.keyword or None,
                    current_page=observation.page,
                    attempt=observation.attempt,
                    elapsed_ms=observation.latency_ms,
                    classification=observation.classification,
                    code=observation.api_code,
                    blocked_url=observation.response_url,
                    retry_reason=observation.retry_reason,
                    stop_reason=observation.stop_reason,
                )
            )
        self.crawl_runtime.write_progress_event(
            crawl_job_id=self.crawl_job_id,
            emitted_by="offertoday-crawl",
            event_type="crawl.listing_page_attempt",
            payload=_production_listing_observation_payload(observation),
        )

    async def record_condition_outcome(self, outcome) -> None:
        suffix = (
            "completed"
            if outcome.is_complete
            else "partial"
            if getattr(outcome, "is_partial", False)
            else "incomplete"
        )
        self.crawl_runtime.write_progress_event(
            crawl_job_id=self.crawl_job_id,
            emitted_by="offertoday-crawl",
            event_type=f"crawl.listing_condition_{suffix}",
            payload=listing_observation_to_payload(outcome),
        )

    def pop_success_latency_ms(self, *, condition_id: str, page: int) -> int:
        return self._success_latency_ms.pop((condition_id, page), 0)


class OfferTodayCrawlStagingSink(OfferTodayReconciledListingStagingSink):
    def __init__(
        self,
        *,
        crawl_runtime,
        crawl_job_id,
        skip_existing: bool,
        observation_sink: CrawlJobListingObservationSink,
        crawl_mode: str,
    ) -> None:
        super().__init__(
            crawl_runtime=crawl_runtime,
            crawl_job_id=crawl_job_id,
            skip_existing=skip_existing,
        )
        self.observation_sink = observation_sink
        self.crawl_mode = crawl_mode

    async def stage_page(self, *, condition, page: int, rows) -> None:
        rows_created_before = self.rows_created
        skipped_before = self.skipped_existing
        persistence_started_at = time.perf_counter()
        await super().stage_page(
            condition=condition,
            page=page,
            rows=rows,
        )
        logger.info(
            build_scrape_log_event(
                "SCRAPE_LISTING_BATCH_STAGED",
                source="offertoday",
                crawl_job_id=self.crawl_job_id,
                crawl_phase="listing",
                crawl_mode=self.crawl_mode,
                condition_id=condition.condition_id,
                search_family=condition.search_family,
                category_id=condition.category_id,
                keyword=condition.keyword or None,
                current_page=page,
                elapsed_ms=self.observation_sink.pop_success_latency_ms(
                    condition_id=condition.condition_id,
                    page=page,
                ),
                persist_elapsed_ms=max(
                    int((time.perf_counter() - persistence_started_at) * 1000),
                    0,
                ),
                job_ids=len(rows),
                listings_staged=self.rows_created - rows_created_before,
                jobs_skipped_existing=(
                    self.skipped_existing - skipped_before
                ),
                cumulative_pages=self.observation_sink.successful_page_count,
                cumulative_job_ids=self.rows_seen,
                cumulative_listings_staged=self.rows_created,
                cumulative_skipped=self.skipped_existing,
            )
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
    stop_reason = str(result.stop_reason)
    stopping_observation = next(
        (
            observation
            for observation in reversed(tuple(result.observations))
            if str(getattr(observation, "stop_reason", "") or "") == stop_reason
            or str(getattr(observation, "classification", "") or "")
            == stop_reason
        ),
        None,
    )
    evidence = {
        "stop_reason": stop_reason,
        "gap_count": len(result.gaps),
        "conflict_count": len(result.identity_conflicts),
        "identity_issue_count": len(result.identity_issues),
        "pages_observed": sum(
            int(getattr(outcome, "pages_observed", 0) or 0)
            for outcome in result.condition_outcomes
        ),
        "accepted_job_id_count": len(result.accepted_job_ids),
        "listing_partial": bool(getattr(result, "is_partial", False)),
        "capped_condition_ids": list(
            getattr(result, "capped_condition_ids", ())
        ),
    }
    if stopping_observation is not None:
        blocked_url = str(
            getattr(stopping_observation, "response_url", "") or ""
        ).strip()
        if blocked_url:
            evidence["blocked_url"] = blocked_url
        code = getattr(stopping_observation, "api_code", None)
        if code is not None:
            evidence["code"] = code
    return evidence


def _listing_metrics(result, staging_sink) -> dict[str, Any]:
    reconciliation = staging_sink.reconciliation
    accepted_ids = set(result.accepted_job_ids)
    supplemental_ids = set(getattr(result, "supplemental_job_ids", ()))
    outcomes = tuple(result.condition_outcomes)
    capped_condition_ids = tuple(
        getattr(result, "capped_condition_ids", ())
    )
    return {
        "listing_partial": bool(getattr(result, "is_partial", False)),
        "listing_condition_count": len(outcomes),
        "listing_natural_condition_count": sum(
            bool(getattr(outcome, "is_complete", False)) for outcome in outcomes
        ),
        "listing_capped_condition_count": len(capped_condition_ids),
        "listing_capped_condition_ids": list(capped_condition_ids),
        "distinct_it_result_ids": len(accepted_ids),
        "raw_job_ids_collected": int(
            getattr(staging_sink, "raw_job_ids_collected", 0) or 0
        ),
        "supplemental_rows_observed": int(
            getattr(result, "supplemental_rows_observed", 0) or 0
        ),
        "distinct_supplemental_ids": len(supplemental_ids),
        "supplemental_result_overlap_count": len(
            accepted_ids & supplemental_ids
        ),
        "supplemental_identity_issue_count": int(
            getattr(result, "supplemental_identity_issue_count", 0) or 0
        ),
        "complete_existing_skipped": len(
            reconciliation.complete_existing_source_job_ids
        ),
        "terminal_unavailable_skipped": len(
            reconciliation.terminal_unavailable_source_job_ids
        ),
        "new_detail_targets": len(reconciliation.new_source_job_ids),
        "repair_detail_targets": len(reconciliation.repair_source_job_ids),
        "detail_success": 0,
        "detail_failure": 0,
    }


async def _run_listing_phase(
    args,
    browser_runtime,
    crawl_runtime,
    crawl_job_id,
    listing_runner=OfferTodayListingRunner,
) -> ProductionListingPhaseResult:
    cancellation_token = resolve_cancellation_token(args)
    phase_started_at = time.perf_counter()
    crawl_mode = "headed" if args.headed else "headless"
    category_ids = _parse_catalog_classification_ids(args.category_ids)
    keywords = normalize_offertoday_keywords(args.keywords)
    conditions = _build_request_listing_conditions(
        args.category_ids,
        keywords=keywords,
    )
    observation_sink = CrawlJobListingObservationSink(
        crawl_runtime=crawl_runtime,
        crawl_job_id=crawl_job_id,
        crawl_mode=crawl_mode,
        cancellation_token=cancellation_token,
    )
    staging_sink = OfferTodayCrawlStagingSink(
        crawl_runtime=crawl_runtime,
        crawl_job_id=crawl_job_id,
        skip_existing=bool(args.skip_existing),
        observation_sink=observation_sink,
        crawl_mode=crawl_mode,
    )
    runner = listing_runner(browser_runtime) if isinstance(listing_runner, type) else listing_runner
    if hasattr(runner, "_sleep"):
        runner._sleep = cancellation_token.sleep

    try:
        cancellation_token.raise_if_cancelled()
        await browser_runtime.require_healthy_session()
        result = await runner.run(
            conditions=conditions,
            stop_policy=ListingStopPolicy(
                max_pages_per_condition=min(
                    int(args.max_pages),
                    MAX_PAGES_GLOBAL,
                ),
                unique_job_cap=None,
                require_empty_confirmation=True,
                page_cap_behavior="retain-and-continue",
            ),
            retry_policy=ListingRetryPolicy(
                max_attempts_per_page=3,
                retry_delays_seconds=(1.0, 2.0),
                page_delay_seconds=1.5,
            ),
            observation_sink=observation_sink,
            staging_sink=staging_sink,
            session_mode=crawl_mode,
            request_policy=production_offertoday_listing_request_policy(),
            terminal_policy="result-transition-confirmation-v1",
        )
    except ManualActionRequiredError as exc:
        logger.warning(
            build_scrape_log_event(
                "SCRAPE_LISTING_MANUAL_ACTION",
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="listing",
                crawl_mode=crawl_mode,
                classification=exc.classification,
                code=exc.code,
                stage=exc.stage,
                blocked_url=exc.blocked_url,
                cumulative_pages=observation_sink.successful_page_count,
                cumulative_job_ids=staging_sink.rows_seen,
                cumulative_raw_job_ids=staging_sink.raw_job_ids_collected,
                cumulative_listings_staged=staging_sink.rows_created,
            )
        )
        logger.info(
            build_scrape_log_event(
                "SCRAPE_LISTING_DONE",
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="listing",
                crawl_mode=crawl_mode,
                outcome="manual_action_required",
                elapsed_ms=max(
                    int((time.perf_counter() - phase_started_at) * 1000),
                    0,
                ),
                conditions=len(conditions),
                pages_processed=observation_sink.successful_page_count,
                job_ids_collected=staging_sink.rows_seen,
                raw_job_ids_collected=staging_sink.raw_job_ids_collected,
                listings_staged=staging_sink.rows_created,
                jobs_skipped_existing=staging_sink.skipped_existing,
            )
        )
        raise
    except Exception as exc:
        logger.warning(
            build_scrape_log_event(
                "SCRAPE_LISTING_PAGE_FAIL",
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="listing",
                crawl_mode=crawl_mode,
                error_type=type(exc).__name__,
                cumulative_pages=observation_sink.successful_page_count,
                cumulative_job_ids=staging_sink.rows_seen,
                cumulative_raw_job_ids=staging_sink.raw_job_ids_collected,
                cumulative_listings_staged=staging_sink.rows_created,
            )
        )
        logger.info(
            build_scrape_log_event(
                "SCRAPE_LISTING_DONE",
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="listing",
                crawl_mode=crawl_mode,
                outcome="failed",
                elapsed_ms=max(
                    int((time.perf_counter() - phase_started_at) * 1000),
                    0,
                ),
                conditions=len(conditions),
                pages_processed=observation_sink.successful_page_count,
                job_ids_collected=staging_sink.rows_seen,
                raw_job_ids_collected=staging_sink.raw_job_ids_collected,
                listings_staged=staging_sink.rows_created,
                jobs_skipped_existing=staging_sink.skipped_existing,
            )
        )
        raise
    execution = ProductionListingPhaseResult(
        listing_result=result,
        staging_sink=staging_sink,
        observation_sink=observation_sink,
    )
    evidence = _listing_result_evidence(result)
    if not getattr(result, "can_proceed_to_detail", result.is_complete):
        stop_reason = str(result.stop_reason)
        manual_action_classifications = (
            RESUMABLE_SESSION_CLASSIFICATIONS | _IDENTITY_AUDIT_CLASSIFICATIONS
        )
        if stop_reason in manual_action_classifications:
            request_payload = _build_runtime_request_payload(
                args,
                crawl_phase="listing",
                source_listing_crawl_job_id=str(crawl_job_id),
            )
            manual_payload = _build_result_manual_action_payload(
                crawl_phase="listing",
                classification=stop_reason,
                evidence=evidence,
                request_payload=request_payload,
            )
            crawl_runtime.mark_manual_action_required(
                crawl_job_id=crawl_job_id,
                source_site="offertoday",
                request_payload=request_payload,
                payload=manual_payload,
                error_message=str(manual_payload["message"]),
            )
            logger.warning(
                build_scrape_log_event(
                    "SCRAPE_LISTING_MANUAL_ACTION",
                    source="offertoday",
                    crawl_job_id=crawl_job_id,
                    crawl_phase="listing",
                    crawl_mode=crawl_mode,
                    classification=stop_reason,
                    code=manual_payload.get("code"),
                    stage=manual_payload.get("stage") or "listing",
                    blocked_url=manual_payload.get("blocked_url"),
                    cumulative_pages=evidence["pages_observed"],
                    cumulative_job_ids=len(result.accepted_job_ids),
                    cumulative_raw_job_ids=staging_sink.raw_job_ids_collected,
                    cumulative_listings_staged=staging_sink.rows_created,
                )
            )
        else:
            crawl_runtime.mark_failed(
                crawl_job_id=crawl_job_id,
                source_site="offertoday",
                error_message=f"OfferToday listing phase incomplete: {stop_reason}",
                payload=evidence,
            )
        logger.info(
            build_scrape_log_event(
                "SCRAPE_LISTING_DONE",
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="listing",
                crawl_mode=crawl_mode,
                outcome=(
                    "manual_action_required"
                    if stop_reason in manual_action_classifications
                    else "failed"
                ),
                stop_reason=stop_reason,
                elapsed_ms=max(
                    int((time.perf_counter() - phase_started_at) * 1000),
                    0,
                ),
                conditions=len(conditions),
                pages_processed=evidence["pages_observed"],
                job_ids_collected=len(result.accepted_job_ids),
                raw_job_ids_collected=staging_sink.raw_job_ids_collected,
                listings_staged=staging_sink.rows_created,
                jobs_skipped_existing=staging_sink.skipped_existing,
            )
        )
        return execution

    listing_metrics = _listing_metrics(result, staging_sink)
    crawl_runtime.merge_metrics(
        crawl_job_id=crawl_job_id,
        metrics_patch=listing_metrics,
    )
    crawl_runtime.write_progress_event(
        crawl_job_id=crawl_job_id,
        emitted_by="offertoday-crawl",
        event_type="listing_completed",
        payload={
            "phase": 1,
            **listing_metrics,
            "pages_processed": sum(
                int(getattr(outcome, "pages_observed", 0) or 0)
                for outcome in result.condition_outcomes
            ),
            "job_ids_collected": len(result.accepted_job_ids),
            "raw_job_ids_collected": int(staging_sink.raw_job_ids_collected),
            "listings_staged": int(staging_sink.rows_created),
        },
    )

    logger.info(
        build_scrape_log_event(
            "SCRAPE_LISTING_DONE",
            source="offertoday",
            crawl_job_id=crawl_job_id,
            crawl_phase="listing",
            crawl_mode=crawl_mode,
            outcome="completed_partial" if result.is_partial else "completed",
            elapsed_ms=max(
                int((time.perf_counter() - phase_started_at) * 1000),
                0,
            ),
            conditions=len(conditions),
            pages_processed=sum(
                int(getattr(outcome, "pages_observed", 0) or 0)
                for outcome in result.condition_outcomes
            ),
            job_ids_collected=len(result.accepted_job_ids),
            listings_staged=staging_sink.rows_created,
            jobs_skipped_existing=staging_sink.skipped_existing,
        )
    )

    if str(args.crawl_phase or "").strip().lower() == "full":
        detail_load_result = crawl_runtime.load_detail_targets(
            source_site="offertoday",
            request_payload={
                "crawl_phase": "detail",
                "crawl_mode": "headed" if args.headed else "headless",
                "category_ids": category_ids,
                "detail_scope": "listing_batch",
                "source_listing_crawl_job_id": crawl_job_id,
                "detail_limit": int(args.detail_limit),
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
        crawl_runtime.merge_metrics(
            crawl_job_id=crawl_job_id,
            metrics_patch={
                "new_detail_targets": int(
                    getattr(detail_load_result, "new_detail_targets", 0) or 0
                ),
                "repair_detail_targets": int(
                    getattr(detail_load_result, "repair_detail_targets", 0) or 0
                ),
            },
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
    total_target_rows: int = 0
    segments_completed: int = 1
    stop_reason: str | None = None

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
    finalize_crawl: bool = True,
    segment_index: int = 1,
) -> OfferTodayDetailPhaseResult:
    cancellation_token = resolve_cancellation_token(args)
    phase_started_at = time.perf_counter()
    crawl_phase = str(args.crawl_phase or "").strip().lower()
    crawl_mode = "headed" if args.headed else "headless"
    source_listing_crawl_job_id, detail_scope = _resolve_detail_scope(
        args,
        listing_phase_completed=crawl_phase == "full",
    )
    request_payload = _build_runtime_request_payload(
        args,
        crawl_phase="detail",
        source_listing_crawl_job_id=source_listing_crawl_job_id,
        detail_scope=detail_scope,
    )

    try:
        if crawl_phase == "detail":
            cancellation_token.raise_if_cancelled()
            await browser_runtime.require_healthy_session()
        if detail_load_result is None:
            detail_load_result = crawl_runtime.load_detail_targets(
                source_site="offertoday",
                request_payload=request_payload,
                detail_crawl_job_id=crawl_job_id,
            )
    except ManualActionRequiredError as exc:
        logger.warning(
            build_scrape_log_event(
                "SCRAPE_DETAIL_MANUAL_ACTION",
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="detail",
                crawl_mode=crawl_mode,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_scope=detail_scope,
                classification=exc.classification,
                code=exc.code,
                stage=exc.stage,
                blocked_url=exc.blocked_url,
                outcome="manual_action_required",
            )
        )
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_DONE",
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="detail",
                crawl_mode=crawl_mode,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_scope=detail_scope,
                outcome="manual_action_required",
                elapsed_ms=max(
                    int((time.perf_counter() - phase_started_at) * 1000),
                    0,
                ),
                detail_target_rows=0,
                processed=0,
                succeeded=0,
                failed=0,
                saved=0,
            )
        )
        raise
    except Exception as exc:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_DONE",
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="detail",
                crawl_mode=crawl_mode,
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
        "detail_scope": detail_scope,
        "segment_index": int(segment_index),
        "segment_target_rows": int(detail_load_result.target_rows),
        "eligible_distinct_rows_before_segment": int(
            getattr(detail_load_result, "eligible_distinct_target_rows", 0) or 0
        ),
        "continuation": bool(
            int(getattr(detail_load_result, "eligible_distinct_target_rows", 0) or 0)
            > int(detail_load_result.target_rows)
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
            crawl_phase="detail",
            crawl_mode=crawl_mode,
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
        detail_success = int(
            outcome_counts.get(OfferTodayResponseKind.SUCCESS.value, 0)
        )
        terminal_unavailable = int(
            outcome_counts.get(
                OfferTodayResponseKind.TERMINAL_UNAVAILABLE.value,
                0,
            )
        )
        return {
            "jobs_created": jobs_created,
            "jobs_updated": jobs_updated,
            "jobs_reconciled": jobs_reconciled,
            "companies_created": companies_created,
            "companies_updated": companies_updated,
            "terminal_unavailable": terminal_unavailable,
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
            "detail_success": detail_success,
            "detail_failure": max(
                sum(outcome_counts.values())
                - detail_success
                - terminal_unavailable,
                0,
            ),
            "new_detail_targets": int(
                getattr(detail_load_result, "new_detail_targets", 0) or 0
            ),
            "repair_detail_targets": int(
                getattr(detail_load_result, "repair_detail_targets", 0) or 0
            ),
            "detail_scope": detail_scope,
            "detail_segment_index": int(segment_index),
            "detail_segment_target_rows": int(detail_load_result.target_rows),
            "detail_eligible_before_segment": int(
                getattr(detail_load_result, "eligible_distinct_target_rows", 0) or 0
            ),
        }

    def build_result(
        *,
        stop_batch: bool,
        stop_reason: str | None = None,
    ) -> OfferTodayDetailPhaseResult:
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
            total_target_rows=int(detail_load_result.target_rows),
            segments_completed=1,
            stop_reason=stop_reason,
        )

    def log_detail_done(outcome: str) -> None:
        metrics = build_metrics_patch()
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_DONE",
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="detail",
                crawl_mode=crawl_mode,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_scope=detail_scope,
                outcome=outcome,
                elapsed_ms=max(
                    int((time.perf_counter() - phase_started_at) * 1000),
                    0,
                ),
                detail_selected_rows=detail_load_result.selected_rows,
                detail_skipped_existing_rows=(
                    detail_load_result.skipped_existing_rows
                ),
                detail_target_rows=detail_load_result.target_rows,
                processed=metrics["detail_processed_targets"],
                succeeded=metrics["detail_success"],
                failed=metrics["detail_failure"],
                saved=metrics["jobs_saved"],
                terminal_unavailable=metrics["terminal_unavailable"],
                persist_failure=metrics["persist_failure"],
                jobs_reconciled=metrics["jobs_reconciled"],
            )
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
        manual_payload = _build_result_manual_action_payload(
            crawl_phase="detail",
            classification="identity_conflict",
            evidence=evidence,
            request_payload=request_payload,
        )
        crawl_runtime.mark_manual_action_required(
            crawl_job_id=crawl_job_id,
            source_site="offertoday",
            request_payload=request_payload,
            payload=manual_payload,
            error_message=str(manual_payload["message"]),
        )
        logger.warning(
            build_scrape_log_event(
                "SCRAPE_DETAIL_MANUAL_ACTION",
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="detail",
                crawl_mode=crawl_mode,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                classification="identity_conflict",
                stage="detail",
                outcome="manual_action_required",
            )
        )
        log_detail_done("manual_action_required")
        return build_result(
            stop_batch=True,
            stop_reason="manual_action_required",
        )

    async def fetch_detail(*, job_id: str, encrypted_job_id: str):
        cancellation_token.raise_if_cancelled()
        return await _fetch_detail_json_with_identifiers(
            browser_runtime,
            job_id=job_id,
            encrypted_job_id=encrypted_job_id,
        )

    if pipeline is None:
        from app.database import SessionLocal
        from app.repositories.company_repository import CompanyRepository
        from app.repositories.job_repository import JobRepository

        detail_pacing_controller = build_detail_pacing_controller(
            request_payload=request_payload,
            crawl_job_id=crawl_job_id,
            crawl_runtime=crawl_runtime,
            cancellation_owner=args,
            session_factory=SessionLocal,
        )
        pipeline = OfferTodayDetailPipeline(
            session_factory=SessionLocal,
            crawl_runtime=crawl_runtime,
            company_repository=CompanyRepository(),
            job_repository=JobRepository(),
            sleep=cancellation_token.sleep,
            clock=time.monotonic,
            max_attempts=3,
            retry_delays_seconds=(1.0, 2.0),
            detail_pacing_controller=detail_pacing_controller,
        )

    total_targets = int(detail_load_result.target_rows)
    if total_targets == 0:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_TARGETS_EMPTY",
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="detail",
                crawl_mode=crawl_mode,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_scope=detail_scope,
                detail_statuses=",".join(
                    _normalize_detail_statuses(args.detail_statuses)
                ),
                detail_limit=args.detail_limit,
            )
        )
    for index, runtime_target in enumerate(detail_load_result.targets, start=1):
        cancellation_token.raise_if_cancelled()
        item_started_at = time.perf_counter()
        raw_source_job_id = str(
            runtime_target.get("source_job_id") or ""
        ).strip()
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_ITEM_START",
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="detail",
                crawl_mode=crawl_mode,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_index=index,
                detail_total=total_targets,
                source_job_id=raw_source_job_id,
                listing_id=runtime_target.get("listing_id"),
            )
        )
        try:
            target = OfferTodayDetailTarget.from_runtime_target(runtime_target)
            result = await pipeline.process_target(
                target=target,
                detail_crawl_job_id=crawl_job_id,
                fetch_detail=fetch_detail,
                crawl_mode=crawl_mode,
            )
        except CrawlCancellationRequested:
            raise
        except Exception as exc:
            logger.warning(
                build_scrape_log_event(
                    "SCRAPE_DETAIL_ITEM_FAIL",
                    source="offertoday",
                    crawl_job_id=crawl_job_id,
                    crawl_phase="detail",
                    crawl_mode=crawl_mode,
                    source_listing_crawl_job_id=(
                        source_listing_crawl_job_id
                    ),
                    detail_index=index,
                    detail_total=total_targets,
                    source_job_id=raw_source_job_id,
                    elapsed_ms=max(
                        int((time.perf_counter() - item_started_at) * 1000),
                        0,
                    ),
                    outcome="failed",
                    error_type=type(exc).__name__,
                    cumulative_processed=sum(outcome_counts.values()),
                    cumulative_succeeded=outcome_counts.get(
                        OfferTodayResponseKind.SUCCESS.value,
                        0,
                    ),
                    cumulative_saved=jobs_created + jobs_updated,
                )
            )
            log_detail_done("failed")
            raise
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

        current_metrics = build_metrics_patch()
        terminal_event = (
            "SCRAPE_DETAIL_ITEM_OK"
            if result.outcome is OfferTodayResponseKind.SUCCESS
            else "SCRAPE_DETAIL_ITEM_MANUAL_ACTION"
            if result.stop_batch
            else "SCRAPE_DETAIL_ITEM_FAIL"
        )
        terminal_logger = (
            logger.info
            if result.outcome
            in {
                OfferTodayResponseKind.SUCCESS,
                OfferTodayResponseKind.TERMINAL_UNAVAILABLE,
            }
            else logger.warning
        )
        terminal_logger(
            build_scrape_log_event(
                terminal_event,
                source="offertoday",
                crawl_job_id=crawl_job_id,
                crawl_phase="detail",
                crawl_mode=crawl_mode,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_index=index,
                detail_total=total_targets,
                source_job_id=target.identity.job_id,
                elapsed_ms=max(
                    int((time.perf_counter() - item_started_at) * 1000),
                    0,
                ),
                outcome=result.outcome.value,
                classification=result.outcome.value,
                cumulative_processed=current_metrics[
                    "detail_processed_targets"
                ],
                cumulative_succeeded=current_metrics["detail_success"],
                cumulative_failed=current_metrics["detail_failure"],
                cumulative_saved=current_metrics["jobs_saved"],
                cumulative_terminal_unavailable=current_metrics[
                    "terminal_unavailable"
                ],
            )
        )

        if result.stop_batch:
            manual_payload = _build_result_manual_action_payload(
                crawl_phase="detail",
                classification=result.outcome.value,
                evidence={
                    "source_job_id": target.identity.job_id,
                    "listing_ids": [
                        str(listing_id) for listing_id in target.listing_ids
                    ],
                    "detail_index": index,
                    "detail_total": total_targets,
                },
                request_payload=request_payload,
            )
            crawl_runtime.merge_metrics(
                crawl_job_id=crawl_job_id,
                metrics_patch=build_metrics_patch(),
            )
            crawl_runtime.mark_manual_action_required(
                crawl_job_id=crawl_job_id,
                source_site="offertoday",
                request_payload=request_payload,
                payload=manual_payload,
                error_message=str(manual_payload["message"]),
            )
            log_detail_done("manual_action_required")
            return build_result(
                stop_batch=True,
                stop_reason="manual_action_required",
            )

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
    if finalize_crawl:
        try:
            crawl_runtime.mark_completed(
                crawl_job_id=crawl_job_id,
                source_site="offertoday",
                payload=completed_payload,
                metrics=completed_metrics,
            )
        except Exception:
            log_detail_done("failed")
            raise
    log_detail_done("completed")
    return phase_result


async def _run_detail_recovery(
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
    source_listing_crawl_job_id, detail_scope = _resolve_detail_scope(
        args,
        listing_phase_completed=str(args.crawl_phase or "").strip().lower() == "full",
    )
    request_payload = _build_runtime_request_payload(
        args,
        crawl_phase="detail",
        source_listing_crawl_job_id=source_listing_crawl_job_id,
        detail_scope=detail_scope,
    )
    current_load_result = detail_load_result
    segment_index = 1
    cumulative_outcomes: dict[str, int] = {}
    cumulative_target_rows = 0
    jobs_created = 0
    jobs_updated = 0
    companies_created = 0
    companies_updated = 0
    persist_failure = 0
    reconciled_source_job_ids: set[str] = set()
    last_result: OfferTodayDetailPhaseResult | None = None

    def build_cumulative_metrics(
        *,
        backlog_result,
        continuation_state: str,
    ) -> dict[str, Any]:
        detail_success = int(
            cumulative_outcomes.get(OfferTodayResponseKind.SUCCESS.value, 0)
        )
        terminal_unavailable = int(
            cumulative_outcomes.get(
                OfferTodayResponseKind.TERMINAL_UNAVAILABLE.value,
                0,
            )
        )
        processed_targets = sum(cumulative_outcomes.values())
        return {
            **dict(completion_metrics or {}),
            "detail_scope": detail_scope,
            "detail_segment_index": int(segment_index),
            "detail_segments_completed": int(segment_index),
            "detail_target_rows": int(cumulative_target_rows),
            "detail_processed_targets": int(processed_targets),
            "detail_outcomes": dict(cumulative_outcomes),
            "detail_success": detail_success,
            "detail_failure": max(
                processed_targets - detail_success - terminal_unavailable,
                0,
            ),
            "terminal_unavailable": terminal_unavailable,
            "persist_failure": int(persist_failure),
            "jobs_created": int(jobs_created),
            "jobs_updated": int(jobs_updated),
            "jobs_reconciled": len(reconciled_source_job_ids),
            "jobs_saved": int(jobs_created + jobs_updated),
            "items_emitted": int(jobs_created + jobs_updated),
            "companies_created": int(companies_created),
            "companies_updated": int(companies_updated),
            "detail_backlog_pending": int(
                getattr(backlog_result, "eligible_pending_rows", 0) or 0
            ),
            "detail_backlog_failed": int(
                getattr(backlog_result, "eligible_failed_rows", 0) or 0
            ),
            "detail_backlog_manual_action_required": int(
                getattr(backlog_result, "eligible_manual_action_rows", 0) or 0
            ),
            "detail_backlog_remaining": int(
                getattr(backlog_result, "eligible_distinct_target_rows", 0) or 0
            ),
            "detail_continuation_state": continuation_state,
        }

    def build_aggregate_result(
        *,
        stop_batch: bool,
        stop_reason: str | None,
    ) -> OfferTodayDetailPhaseResult:
        assert last_result is not None
        return OfferTodayDetailPhaseResult(
            detail_load_result=last_result.detail_load_result,
            processed_targets=sum(cumulative_outcomes.values()),
            outcome_counts=dict(cumulative_outcomes),
            jobs_created=jobs_created,
            jobs_updated=jobs_updated,
            jobs_reconciled=len(reconciled_source_job_ids),
            companies_created=companies_created,
            companies_updated=companies_updated,
            terminal_unavailable=int(
                cumulative_outcomes.get(
                    OfferTodayResponseKind.TERMINAL_UNAVAILABLE.value,
                    0,
                )
            ),
            persist_failure=persist_failure,
            stop_batch=stop_batch,
            total_target_rows=cumulative_target_rows,
            segments_completed=segment_index,
            stop_reason=stop_reason,
        )

    while True:
        segment_result = await _run_detail_phase(
            args=args,
            browser_runtime=browser_runtime,
            crawl_runtime=crawl_runtime,
            crawl_job_id=crawl_job_id,
            detail_load_result=current_load_result,
            pipeline=pipeline,
            completion_payload=completion_payload,
            completion_metrics=completion_metrics,
            finalize_crawl=False,
            segment_index=segment_index,
        )
        last_result = segment_result
        cumulative_target_rows += int(segment_result.detail_load_result.target_rows)
        for outcome, count in segment_result.outcome_counts.items():
            cumulative_outcomes[outcome] = cumulative_outcomes.get(outcome, 0) + int(count)
        jobs_created += int(segment_result.jobs_created)
        jobs_updated += int(segment_result.jobs_updated)
        companies_created += int(segment_result.companies_created)
        companies_updated += int(segment_result.companies_updated)
        persist_failure += int(segment_result.persist_failure)
        reconciled_source_job_ids.update(
            segment_result.detail_load_result.reconciled_source_job_ids
        )

        next_load_result = crawl_runtime.load_detail_targets(
            source_site="offertoday",
            request_payload=request_payload,
            detail_crawl_job_id=crawl_job_id,
        )
        segment_failure = max(
            segment_result.processed_targets
            - int(
                segment_result.outcome_counts.get(
                    OfferTodayResponseKind.SUCCESS.value,
                    0,
                )
            )
            - int(segment_result.terminal_unavailable),
            0,
        )
        if segment_result.stop_batch:
            metrics = build_cumulative_metrics(
                backlog_result=next_load_result,
                continuation_state="manual_action_required",
            )
            crawl_runtime.merge_metrics(
                crawl_job_id=crawl_job_id,
                metrics_patch=metrics,
            )
            crawl_runtime.write_progress_event(
                crawl_job_id=crawl_job_id,
                emitted_by="offertoday-crawl",
                event_type="crawl.detail_segment",
                payload={
                    "detail_scope": detail_scope,
                    "segment_index": segment_index,
                    "segment_target_rows": int(
                        segment_result.detail_load_result.target_rows
                    ),
                    "continuation_state": "manual_action_required",
                    "detail_backlog_remaining": metrics[
                        "detail_backlog_remaining"
                    ],
                },
            )
            return build_aggregate_result(
                stop_batch=True,
                stop_reason=segment_result.stop_reason or "manual_action_required",
            )

        if segment_failure > 0:
            metrics = build_cumulative_metrics(
                backlog_result=next_load_result,
                continuation_state="failed",
            )
            error_message = (
                "OfferToday detail recovery stopped after a failed segment; "
                f"{metrics['detail_backlog_failed']} failed targets remain."
            )
            crawl_runtime.mark_failed(
                crawl_job_id=crawl_job_id,
                source_site="offertoday",
                error_message=error_message,
                payload={
                    **dict(completion_payload or {}),
                    "detail_scope": detail_scope,
                    "detail_segments_completed": segment_index,
                    "detail_backlog_remaining": metrics[
                        "detail_backlog_remaining"
                    ],
                },
                metrics=metrics,
            )
            return build_aggregate_result(
                stop_batch=True,
                stop_reason="failed",
            )

        if (
            int(next_load_result.target_rows) == 0
            and not next_load_result.identity_conflict_ids
        ):
            reconciled_source_job_ids.update(
                next_load_result.reconciled_source_job_ids
            )
            metrics = build_cumulative_metrics(
                backlog_result=next_load_result,
                continuation_state="completed",
            )
            crawl_runtime.mark_completed(
                crawl_job_id=crawl_job_id,
                source_site="offertoday",
                payload={
                    **dict(completion_payload or {}),
                    "detail_scope": detail_scope,
                    "detail_segments_completed": segment_index,
                    "detail_outcomes": dict(cumulative_outcomes),
                    "jobs_created": jobs_created,
                    "jobs_updated": jobs_updated,
                    "jobs_reconciled": len(reconciled_source_job_ids),
                    "terminal_unavailable": metrics["terminal_unavailable"],
                    "persist_failure": persist_failure,
                },
                metrics=metrics,
            )
            return build_aggregate_result(
                stop_batch=False,
                stop_reason=None,
            )

        continuing_metrics = build_cumulative_metrics(
            backlog_result=next_load_result,
            continuation_state="continuing",
        )
        crawl_runtime.merge_metrics(
            crawl_job_id=crawl_job_id,
            metrics_patch=continuing_metrics,
        )
        crawl_runtime.write_progress_event(
            crawl_job_id=crawl_job_id,
            emitted_by="offertoday-crawl",
            event_type="crawl.detail_segment",
            payload={
                "detail_scope": detail_scope,
                "segment_index": segment_index,
                "segment_target_rows": int(
                    segment_result.detail_load_result.target_rows
                ),
                "continuation_state": "continuing",
                "detail_backlog_remaining": continuing_metrics[
                    "detail_backlog_remaining"
                ],
            },
        )
        current_load_result = next_load_result
        segment_index += 1


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
    args.cancellation_token = CrawlCancellationToken(
        crawl_job_id=args.crawl_job_id,
        execution_generation=args.execution_generation or None,
    )
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

    category_ids = _resolve_published_listing_category_ids(args.category_ids)
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
        _build_request_listing_conditions(
            args.category_ids,
            keywords=keywords,
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
    planned_total_pages = len(listing_conditions) * page_limit_per_query
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
        try:
            args.cancellation_token.raise_if_cancelled()
        except CrawlCancellationRequested:
            logger.info(
                build_scrape_log_event(
                    "SCRAPE_EXECUTOR_CANCELLED",
                    source="offertoday",
                    crawl_job_id=args.crawl_job_id,
                    crawl_phase=crawl_phase,
                    crawl_mode="headed" if args.headed else "headless",
                )
            )
            db.close()
            return
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
    listing_metrics: dict[str, Any] = {}

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

        reuse_browser_channel = None
        reuse_browser_profile_path = None
        if args.resume_strategy == RESUME_STRATEGY_REUSE_OPEN_BROWSER:
            reuse_browser_channel = (
                getattr(args, "manual_action_browser_channel", "") or None
            )
            reuse_browser_profile_path = (
                getattr(args, "manual_action_browser_profile_path", "") or None
            )

        args.cancellation_token.raise_if_cancelled()
        async with OfferTodayBrowserRuntime(
            headed=args.headed,
            auth_state_path=str(auth_state_path) if auth_state_path else None,
            resume_strategy=args.resume_strategy,
            browser_channel=reuse_browser_channel,
            user_data_dir=reuse_browser_profile_path,
            cancellation_token=args.cancellation_token,
        ) as runtime:
            page = runtime._page
            if page is None:
                raise RuntimeError("OfferToday browser runtime did not create a page")

            await _check_and_handle_waf_challenge(
                page,
                headed=args.headed,
                crawl_job_id=cj_id,
                db=db,
                cancellation_token=args.cancellation_token,
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
                listing_metrics = _listing_metrics(
                    listing_result,
                    listing_execution.staging_sink,
                )
                new_jobs_count = int(
                    listing_metrics.get("new_detail_targets", 0) or 0
                )
                jobs_skipped_existing = int(
                    listing_execution.staging_sink.skipped_existing
                )
                page_count = sum(
                    int(outcome.pages_observed or 0)
                    for outcome in listing_result.condition_outcomes
                )
                if listing_result.condition_outcomes:
                    search_family = str(
                        listing_result.condition_outcomes[-1].condition.search_family
                    )
                if not getattr(
                    listing_result,
                    "can_proceed_to_detail",
                    listing_result.is_complete,
                ):
                    logger.warning(
                        "Listing phase incomplete; stop_reason=%s pages=%d",
                        listing_result.stop_reason,
                        page_count,
                    )
                    logger.warning(
                        build_scrape_log_event(
                            "SCRAPE_EXECUTOR_MANUAL_ACTION"
                            if str(listing_result.stop_reason)
                            in (
                                RESUMABLE_SESSION_CLASSIFICATIONS
                                | _IDENTITY_AUDIT_CLASSIFICATIONS
                            )
                            else "SCRAPE_EXECUTOR_FAIL",
                            source="offertoday",
                            crawl_job_id=cj_id,
                            crawl_phase="listing",
                            crawl_mode=(
                                "headed" if args.headed else "headless"
                            ),
                            classification=listing_result.stop_reason,
                            pages_processed=page_count,
                            listings_staged=listing_count,
                        )
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
                detail_phase_result = await _run_detail_recovery(
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
                        **listing_metrics,
                        "pages_processed": page_count,
                        "job_ids_collected": len(seen_ids),
                        "listings_staged": listing_count,
                        "new_jobs_added": new_jobs_count,
                        "jobs_skipped_existing": jobs_skipped_existing,
                        "search_families": search_families,
                    },
                )
                total_details = int(detail_phase_result.total_target_rows)
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
                    executor_event = (
                        "SCRAPE_EXECUTOR_FAIL"
                        if detail_phase_result.stop_reason == "failed"
                        else "SCRAPE_EXECUTOR_MANUAL_ACTION"
                    )
                    logger.warning(
                        build_scrape_log_event(
                            executor_event,
                            source="offertoday",
                            crawl_job_id=cj_id,
                            crawl_phase="detail",
                            crawl_mode=(
                                "headed" if args.headed else "headless"
                            ),
                            source_listing_crawl_job_id=(
                                source_listing_crawl_job_id
                            ),
                            detail_processed=(
                                detail_phase_result.processed_targets
                            ),
                            stop_reason=detail_phase_result.stop_reason,
                        )
                    )
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
                    **listing_metrics,
                    "pages_processed": page_count,
                    "job_ids_collected": len(seen_ids),
                    "listings_staged": listing_count,
                    "new_jobs_added": new_jobs_count,
                    "jobs_skipped_existing": jobs_skipped_existing,
                    "current_page": page_count,
                    "total_pages": planned_total_pages,
                    "detail_selected_rows": detail_selected_rows,
                    "detail_skipped_existing_rows": detail_skipped_existing_rows,
                    "detail_target_rows": total_details,
                    "detail_pending": 0,
                    "items_emitted": 0,
                    "jobs_saved": 0,
                    "search_family": search_family,
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

    except CrawlCancellationRequested:
        logger.info(
            build_scrape_log_event(
                "SCRAPE_EXECUTOR_CANCELLED",
                source="offertoday",
                crawl_job_id=cj_id,
                crawl_phase=crawl_phase,
                crawl_mode="headed" if args.headed else "headless",
            )
        )
    except OfferTodayListingIdentityConflictError as exc:
        logger.warning("Crawl paused for listing identity audit: %s", exc)
        if args.crawl_job_id:
            logger.warning(
                build_scrape_log_event(
                    "SCRAPE_EXECUTOR_MANUAL_ACTION",
                    source="offertoday",
                    crawl_job_id=cj_id,
                    crawl_phase="listing",
                    crawl_mode="headed" if args.headed else "headless",
                    classification="identity_conflict",
                    error_type=type(exc).__name__,
                )
            )
            request_payload = _build_runtime_request_payload(
                args,
                crawl_phase="listing",
                source_listing_crawl_job_id=str(cj_id),
            )
            manual_payload = _build_result_manual_action_payload(
                crawl_phase="listing",
                classification="identity_conflict",
                evidence={
                    "identity_conflict_ids": list(exc.source_job_ids),
                    "identity_conflict_evidence": [
                        dict(item) for item in exc.evidence
                    ],
                },
                request_payload=request_payload,
            )
            crawl_runtime.mark_manual_action_required(
                crawl_job_id=cj_id,
                source_site="offertoday",
                request_payload=request_payload,
                payload=manual_payload,
                error_message=str(manual_payload["message"]),
            )
    except ManualActionRequiredError as exc:
        logger.warning("Crawl paused for manual action: %s", exc.message)
        if args.crawl_job_id:
            resume_crawl_phase = "detail" if crawl_phase == "detail" else "listing"
            resume_source_listing_crawl_job_id = source_listing_crawl_job_id
            if resume_crawl_phase == "listing":
                resume_source_listing_crawl_job_id = str(cj_id)
            logger.warning(
                build_scrape_log_event(
                    "SCRAPE_EXECUTOR_MANUAL_ACTION",
                    source="offertoday",
                    crawl_job_id=cj_id,
                    crawl_phase=resume_crawl_phase,
                    crawl_mode="headed" if args.headed else "headless",
                    classification=exc.classification,
                    code=exc.code,
                    stage=exc.stage,
                    blocked_url=exc.blocked_url,
                )
            )
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
        logger.exception(
            build_scrape_log_event(
                "SCRAPE_EXECUTOR_FAIL",
                source="offertoday",
                crawl_job_id=cj_id,
                crawl_phase=crawl_phase,
                crawl_mode="headed" if args.headed else "headless",
                error_type=type(exc).__name__,
            )
        )
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
