#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.scraper.manual_action import (  # noqa: E402
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
)
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime  # noqa: E402
from app.sources.offertoday.constants import build_offertoday_listing_payload  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("offertoday-bakeoff")


@dataclass
class TransportResult:
    name: str
    listing_success: bool = False
    listing_count: int = 0
    listing_elapsed: float = 0.0
    listing_error: str | None = None
    detail_success_count: int = 0
    detail_attempted: int = 0
    detail_elapsed: float = 0.0
    detail_errors: list[str] = field(default_factory=list)


async def _run_candidate(
    *,
    name: str,
    headed: bool,
    resume_strategy: str,
    auth_state_path: str | None,
    category_id: int,
    keyword: str,
    detail_limit: int,
) -> TransportResult:
    result = TransportResult(name=name)
    listing_payload = build_offertoday_listing_payload(
        category_id=category_id,
        keyword=keyword,
        page=1,
    )

    try:
        async with OfferTodayBrowserRuntime(
            headed=headed,
            auth_state_path=auth_state_path,
            resume_strategy=resume_strategy,
        ) as runtime:
            t0 = time.monotonic()
            smoke = await runtime.run_smoke_test(
                listing_payload=listing_payload,
                detail_limit=detail_limit,
            )
            elapsed = time.monotonic() - t0
    except Exception as exc:
        result.listing_error = str(exc)
        return result

    detail_results = list(smoke.get("detail_results") or [])
    result.listing_success = bool(smoke.get("listing_ok"))
    result.listing_count = int(smoke.get("listing_count") or 0)
    result.listing_elapsed = elapsed
    result.detail_attempted = len(detail_results)
    result.detail_success_count = sum(1 for row in detail_results if row.get("code") == 0)
    result.detail_elapsed = elapsed
    result.detail_errors = [
        f'{row.get("job_id")}: code={row.get("code")}'
        for row in detail_results
        if row.get("code") != 0
    ]
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description="OfferToday runtime bakeoff / smoke comparison")
    parser.add_argument("--category", type=int, default=112000, help="Category ID for the listing probe.")
    parser.add_argument("--keywords", type=str, default="", help="Keyword probe.")
    parser.add_argument("--details", type=int, default=3, help="Number of detail probes.")
    parser.add_argument(
        "--auth-state",
        default="",
        help="Optional OfferToday storage_state JSON to test the storage-state path.",
    )
    args = parser.parse_args()

    logger.info(
        "OfferToday runtime bakeoff: category=%d keyword=%s details=%d",
        args.category,
        args.keywords,
        args.details,
    )

    results: list[TransportResult] = []
    results.append(
        await _run_candidate(
            name="fresh-profile",
            headed=False,
            resume_strategy=RESUME_STRATEGY_FRESH_PROFILE,
            auth_state_path=None,
            category_id=args.category,
            keyword=args.keywords,
            detail_limit=args.details,
        )
    )
    if args.auth_state:
        results.append(
            await _run_candidate(
                name="storage-state",
                headed=False,
                resume_strategy=RESUME_STRATEGY_FRESH_PROFILE,
                auth_state_path=args.auth_state,
                category_id=args.category,
                keyword=args.keywords,
                detail_limit=args.details,
            )
        )
    results.append(
        await _run_candidate(
            name="reuse-open-browser",
            headed=True,
            resume_strategy=RESUME_STRATEGY_REUSE_OPEN_BROWSER,
            auth_state_path=None,
            category_id=args.category,
            keyword=args.keywords,
            detail_limit=args.details,
        )
    )

    logger.info("\n=== BAKEOFF SUMMARY ===")
    for result in results:
        logger.info(
            "%s | listing_ok=%s listing_count=%d detail=%d/%d errors=%s",
            result.name,
            result.listing_success,
            result.listing_count,
            result.detail_success_count,
            result.detail_attempted,
            result.detail_errors or "[]",
        )


if __name__ == "__main__":
    asyncio.run(main())
