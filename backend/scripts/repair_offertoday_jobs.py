#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.scraper.manual_action import (
    RESUME_STRATEGY_FRESH_PROFILE,
    ManualActionRequiredError,
)
from app.scraper.offertoday_browser_detail_scraper import OfferTodayBrowserDetailScraper
from app.scraper.offertoday_pacing import pause_before_detail_request
from app.services.offertoday_job_repair_service import OfferTodayJobRepairService
from app.sources.offertoday.detail_identity import OfferTodayIdentityError
from app.sources.offertoday.response_policy import OfferTodayResponseKind


async def repair_jobs(
    *,
    limit: int | None = None,
    execute: bool = False,
    live_fetch_missing: bool = True,
    auth_state_path: str | None = None,
    headed: bool = False,
    resume_strategy: str = RESUME_STRATEGY_FRESH_PROFILE,
    manual_verification_timeout_seconds: int = 180,
) -> dict[str, int]:
    db = SessionLocal()
    try:
        service = OfferTodayJobRepairService(db)
        jobs = service.iter_repair_candidates(limit=limit)

        cached_repaired_descriptions = 0
        live_repaired_descriptions = 0
        reassigned_companies = 0
        attached_listings = 0
        cached_updated_jobs = 0
        cached_created_jobs = 0
        live_updated_jobs = 0
        live_created_jobs = 0
        live_fetch_failed = 0
        live_terminal_unavailable = 0
        live_ip_blocked = False
        live_ip_blocked_job_id = None

        for job in jobs:
            result = service.repair_job(job)
            if result.description_repaired:
                cached_repaired_descriptions += 1
            if result.company_reassigned:
                reassigned_companies += 1
            if result.listing_attached:
                attached_listings += 1
            if result.action == "updated":
                cached_updated_jobs += 1
            elif result.action == "created":
                cached_created_jobs += 1

        if live_fetch_missing:
            live_candidates = [job for job in jobs if service.is_degraded_job(job)]
            if live_candidates:
                async with OfferTodayBrowserDetailScraper(
                    request_payload={"resume_strategy": resume_strategy},
                    auth_state_path=auth_state_path,
                    headed=headed,
                    manual_verification_timeout_seconds=manual_verification_timeout_seconds,
                ) as scraper:
                    for job in live_candidates:
                        listing = service.get_latest_listing(job.source_job_id)
                        try:
                            job_id, encrypted_job_id = (
                                service.resolve_detail_identifiers(
                                    job,
                                    listing,
                                )
                            )
                            await pause_before_detail_request()
                            detail_result = await scraper.fetch_job_detail(
                                job_id,
                                encrypted_job_id=encrypted_job_id,
                            )
                        except OfferTodayIdentityError as exc:
                            live_fetch_failed += 1
                            if listing is not None:
                                listing.detail_status = "failed"
                                listing.detail_error_message = str(exc)
                                listing.detail_completed_at = datetime.now(UTC)
                            continue

                        result = service.repair_job_with_detail_result(
                            job, detail_result
                        )
                        classification = detail_result.classification
                        if classification.kind is OfferTodayResponseKind.IP_BLOCKED:
                            live_ip_blocked = True
                            live_ip_blocked_job_id = detail_result.identity.job_id
                            break
                        if (
                            classification.kind
                            is OfferTodayResponseKind.TERMINAL_UNAVAILABLE
                        ):
                            live_terminal_unavailable += 1
                            continue
                        if classification.kind is not OfferTodayResponseKind.SUCCESS:
                            live_fetch_failed += 1
                            if classification.stop_batch:
                                break
                            continue
                        if result.description_repaired:
                            live_repaired_descriptions += 1
                        if result.company_reassigned:
                            reassigned_companies += 1
                        if result.listing_attached:
                            attached_listings += 1
                        if result.action == "updated":
                            live_updated_jobs += 1
                        elif result.action == "created":
                            live_created_jobs += 1

        remaining_missing = len([job for job in jobs if service.is_degraded_job(job)])

        if execute:
            db.commit()
        else:
            db.rollback()

        return {
            "scanned_jobs": len(jobs),
            "cached_repaired_descriptions": cached_repaired_descriptions,
            "live_repaired_descriptions": live_repaired_descriptions,
            "repaired_descriptions": cached_repaired_descriptions
            + live_repaired_descriptions,
            "reassigned_companies": reassigned_companies,
            "attached_listings": attached_listings,
            "cached_updated_jobs": cached_updated_jobs,
            "cached_created_jobs": cached_created_jobs,
            "live_updated_jobs": live_updated_jobs,
            "live_created_jobs": live_created_jobs,
            "updated_jobs": cached_updated_jobs + live_updated_jobs,
            "created_jobs": cached_created_jobs + live_created_jobs,
            "live_fetch_failed": live_fetch_failed,
            "live_terminal_unavailable": live_terminal_unavailable,
            "live_ip_blocked": int(live_ip_blocked),
            "live_ip_blocked_job_id": live_ip_blocked_job_id,
            "remaining_missing_descriptions": remaining_missing,
            "committed": int(execute),
        }
    except ManualActionRequiredError:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repair stored OfferToday jobs using cached detail payloads."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of OfferToday jobs to inspect.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Persist repaired jobs and company assignments. Default is dry-run.",
    )
    parser.add_argument(
        "--skip-live-fetch",
        action="store_true",
        default=False,
        help="Only repair from cached OfferToday payloads; do not re-fetch missing live details.",
    )
    parser.add_argument(
        "--auth-state",
        default="",
        help="Optional Playwright storage_state JSON file for OfferToday live detail fetches.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        default=False,
        help="Run OfferToday live detail repair in a visible browser so WAF verification can be completed manually.",
    )
    parser.add_argument(
        "--resume-strategy",
        default=RESUME_STRATEGY_FRESH_PROFILE,
        choices=("fresh_profile", "reuse_open_browser"),
        help="How live detail repair should create or attach to the browser session.",
    )
    parser.add_argument(
        "--manual-timeout",
        type=int,
        default=180,
        help="Seconds to wait for manual OfferToday WAF verification in headed mode. Default: 180.",
    )
    args = parser.parse_args()

    result = asyncio.run(
        repair_jobs(
            limit=args.limit,
            execute=args.execute,
            live_fetch_missing=not args.skip_live_fetch,
            auth_state_path=args.auth_state or None,
            headed=args.headed,
            resume_strategy=args.resume_strategy,
            manual_verification_timeout_seconds=args.manual_timeout,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
