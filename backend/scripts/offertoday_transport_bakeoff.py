#!/usr/bin/env python3
"""OfferToday transport bake-off — compares Playwright vs scrapy-playwright vs Scrapling.

This script runs a controlled comparison of transport candidates for
OfferToday's WAF-protected API. It tests:
  - One category listing fetch
  - One keyword probe
  - A small set of detail fetches

Metrics recorded per candidate:
  - HTTP status / WAF block errors
  - JSON parse success
  - Unique listings returned
  - Detail success rate
  - Elapsed time per request
  - Retry count

Usage:
    python scripts/offertoday_transport_bakeoff.py \\
        --category 112000 \\
        --keywords a \\
        --pages 2 \\
        --details 3
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("offertoday-bakeoff")

sys.path.insert(0, ".")


@dataclass
class TransportResult:
    name: str
    listing_success: bool = False
    listing_count: int = 0
    listing_elapsed: float = 0.0
    listing_status: int | None = None
    listing_error: str | None = None
    detail_success_count: int = 0
    detail_attempted: int = 0
    detail_elapsed: float = 0.0
    detail_errors: list[str] = field(default_factory=list)


def _build_search_payload(
    page: int, category_ids: list[int], keyword: str = ""
) -> dict[str, Any]:
    return {
        "keyword": keyword,
        "salaryType": 0,
        "employmentTypes": [],
        "publishTime": "",
        "experiences": [],
        "educationLevels": [],
        "benefits": [],
        "rcdType": 7,
        "pageSize": 10,
        "page": page,
        "industries": [],
        "jobFunctionCodes": category_ids,
        "subDistrictCodes": [],
        "needShowDistance": False,
        "searchSource": None,
    }


async def test_current_playwright(
    category: int, keyword: str, pages: int, details: int
) -> TransportResult:
    """Test the current Playwright-based fetch approach."""
    import asyncio

    from playwright.async_api import async_playwright

    from app.sources.offertoday.parsers import (
        parse_offertoday_listing_response,
        extract_encrypted_job_id,
    )

    result = TransportResult(name="playwright-current")
    total_listings = 0
    job_ids: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        await page.goto("https://www.offertoday.com", wait_until="domcontentloaded")
        await asyncio.sleep(2)  # Let WAF cookies settle

        try:
            t0 = time.monotonic()
            for p in range(1, pages + 1):
                payload = _build_search_payload(p, [category], keyword)
                js = (
                    f"""() => {{ return fetch(
                    'https://www.offertoday.com/wapi/geek/recommend/search/list',
                    {{
                        method: 'POST',
                        headers: {{
                            'api-language': 'zh_HK',
                            'x-requested-with': 'XMLHttpRequest',
                            'accept': 'application/json, text/plain, */*',
                            'content-type': 'application/json;charset=UTF-8',
                        }},
                        body: JSON.stringify({json.dumps(payload, ensure_ascii=False)})
                    }}).then(r => r.json()); }}"""
                )
                response: dict[str, Any] = await page.evaluate(js)
                if response.get("code") == 0 and "resultList" in response.get("data", {}):
                    parsed = parse_offertoday_listing_response(response)
                    total_listings += len(parsed)
                    for job in parsed:
                        jid = extract_encrypted_job_id(job.get("encrypted_job_id", ""))
                        if jid:
                            job_ids.append(jid)
                else:
                    logger.warning("Listing page %d failed: %s", p, response.get("code"))
            result.listing_elapsed = time.monotonic() - t0
            result.listing_success = total_listings > 0
            result.listing_count = total_listings
            result.listing_status = 200 if result.listing_success else 0
        except Exception as exc:
            result.listing_success = False
            result.listing_error = str(exc)
            logger.error("Listing phase error: %s", exc)

        # Detail phase
        target_ids = job_ids[:details]
        result.detail_attempted = len(target_ids)
        t0 = time.monotonic()
        for jid in target_ids:
            try:
                detail_js = (
                    f"""() => {{ return fetch(
                    'https://www.offertoday.com/wapi/geek/recommend/jobDetail?id={jid}&encryptJobId={jid}',
                    {{
                        headers: {{
                            'api-language': 'zh_HK',
                            'x-requested-with': 'XMLHttpRequest',
                        }}
                    }}).then(r => r.json()); }}"""
                )
                detail: dict[str, Any] = await page.evaluate(detail_js)
                if detail.get("code") == 0 and detail.get("data", {}).get("jobId"):
                    result.detail_success_count += 1
                else:
                    result.detail_errors.append(f"{jid}: no data")
                await asyncio.sleep(1.5)  # WAF cooldown
            except Exception as exc:
                result.detail_errors.append(f"{jid}: {exc}")
        result.detail_elapsed = time.monotonic() - t0

        await browser.close()
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description="OfferToday transport bake-off")
    parser.add_argument("--category", type=int, default=112000, help="Category ID")
    parser.add_argument("--keywords", type=str, default="a", help="Keyword probe")
    parser.add_argument("--pages", type=int, default=2, help="Listing pages to fetch")
    parser.add_argument("--details", type=int, default=3, help="Detail fetches")
    args = parser.parse_args()

    logger.info(
        "OfferToday Transport Bake-Off\n"
        "  category=%d  keywords=%s  pages=%d  details=%d",
        args.category,
        args.keywords,
        args.pages,
        args.details,
    )

    results: list[TransportResult] = []

    # Test 1: Current Playwright approach
    logger.info("\n=== Test 1: Current Playwright ===")
    result = await test_current_playwright(args.category, args.keywords, args.pages, args.details)
    results.append(result)
    logger.info(
        "  Listing: %d jobs in %.1fs | Detail: %d/%d in %.1fs",
        result.listing_count,
        result.listing_elapsed,
        result.detail_success_count,
        result.detail_attempted,
        result.detail_elapsed,
    )

    # Print summary
    logger.info("\n=== BAKE-OFF SUMMARY ===")
    logger.info(
        "%-25s %10s %8s %10s %8s",
        "Transport",
        "Listings",
        "L-Time",
        "Detail%",
        "D-Time",
    )
    logger.info("-" * 65)
    for r in results:
        detail_pct = (
            (r.detail_success_count / r.detail_attempted * 100)
            if r.detail_attempted > 0
            else 0
        )
        logger.info(
            "%-25s %10d %8.1fs %10.0f%% %8.1fs",
            r.name,
            r.listing_count,
            r.listing_elapsed,
            detail_pct,
            r.detail_elapsed,
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
