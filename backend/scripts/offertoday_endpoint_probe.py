#!/usr/bin/env python3
"""Quick probe: compare data.total across endpoints and rcdType values.

Run inside the backend container:
    python backend/scripts/offertoday_endpoint_probe.py

Probes each test condition twice — once with search/list (current) and once
with the plain browse /list endpoint — and prints the API-reported totals side
by side so we can confirm whether the endpoint or rcdType is the bottleneck.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BACKEND = str(Path(__file__).resolve().parents[1])
SCRAPY = str(Path(__file__).resolve().parents[1] / "scrapy_project")
for p in (BACKEND, SCRAPY):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.sources.offertoday.constants import (
    OFFERTODAY_BASE_URL,
    OFFERTODAY_COMMON_HEADERS,
    OFFERTODAY_LISTING_BROWSE_URL,
    OFFERTODAY_LISTING_SEARCH_URL,
)

WARMUP_URL = f"{OFFERTODAY_BASE_URL}/hk/search"

# Conditions to probe: (label, category_id_or_None, keyword, rcdType)
# These are known to show hundreds of results on the website per the user.
PROBE_CONDITIONS = [
    # Keywords the user confirmed show 400-800 results on website
    ("ERP / search",       None, "ERP",      7, OFFERTODAY_LISTING_SEARCH_URL),
    ("ERP / browse",       None, "ERP",      7, OFFERTODAY_LISTING_BROWSE_URL),
    ("Java / search",      None, "Java",     7, OFFERTODAY_LISTING_SEARCH_URL),
    ("Java / browse",      None, "Java",     7, OFFERTODAY_LISTING_BROWSE_URL),
    ("security / search",  None, "security", 7, OFFERTODAY_LISTING_SEARCH_URL),
    ("security / browse",  None, "security", 7, OFFERTODAY_LISTING_BROWSE_URL),
    # IT root category — both endpoints
    ("IT cat / search",    118000, "",       7, OFFERTODAY_LISTING_SEARCH_URL),
    ("IT cat / browse",    118000, "",       7, OFFERTODAY_LISTING_BROWSE_URL),
    # rcdType variation on search endpoint
    ("ERP rcdType=1",      None, "ERP",      1, OFFERTODAY_LISTING_SEARCH_URL),
    ("ERP rcdType=2",      None, "ERP",      2, OFFERTODAY_LISTING_SEARCH_URL),
    ("ERP rcdType=0",      None, "ERP",      0, OFFERTODAY_LISTING_SEARCH_URL),
]


def _build_payload(
    keyword: str,
    category_id: int | None,
    page: int,
    rcd_type: int,
) -> dict:
    payload: dict = {
        "keyword": keyword,
        "rcdType": rcd_type,
        "pageSize": 50,
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


async def probe_condition(
    page,
    label: str,
    category_id: int | None,
    keyword: str,
    rcd_type: int,
    endpoint: str,
) -> dict:
    payload = _build_payload(keyword, category_id, 1, rcd_type)
    js = f"""() => {{
        return fetch('{endpoint}', {{
            method: 'POST',
            headers: {json.dumps(OFFERTODAY_COMMON_HEADERS, ensure_ascii=False)},
            body: JSON.stringify({json.dumps(payload, ensure_ascii=False)})
        }}).then(r => r.json()).catch(e => ({{error: e.toString()}}));
    }}"""
    try:
        result = await page.evaluate(js)
    except Exception as exc:
        return {"label": label, "error": str(exc), "total": -1, "page1_count": -1, "code": -1}

    code = result.get("code") if isinstance(result, dict) else -1
    data = result.get("data") or {} if isinstance(result, dict) else {}
    total = int(data.get("total") or 0)
    result_list = data.get("resultList") or []
    page1_count = len(result_list)
    error = result.get("error") if isinstance(result, dict) else str(result)

    return {
        "label": label,
        "code": code,
        "total": total,
        "page1_count": page1_count,
        "error": error if code != 0 else None,
    }


async def main() -> None:
    from playwright.async_api import async_playwright

    print("=" * 75)
    print("OfferToday Endpoint Probe")
    print("=" * 75)
    print(f"{'Label':<25} {'Code':>5} {'API total':>10} {'Page1 rows':>10}")
    print("-" * 75)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="zh-HK",
        )
        page = await context.new_page()

        print("Warming up browser session...")
        await page.goto(WARMUP_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        print("Warmup done. Starting probes...\n")

        for (label, cat_id, kw, rcd, endpoint) in PROBE_CONDITIONS:
            r = await probe_condition(page, label, cat_id, kw, rcd, endpoint)
            status = f"code={r['code']}" if r["code"] != 0 else "OK"
            err = f"  ← {r['error']}" if r.get("error") else ""
            print(
                f"{r['label']:<25} {str(r['code']):>5} {r['total']:>10} {r['page1_count']:>10}"
                f"  {status}{err}"
            )
            await asyncio.sleep(1)  # small WAF cooldown between calls

        await browser.close()

    print("\n" + "=" * 75)
    print("INTERPRETATION:")
    print("  If 'browse' total >> 'search' total for same keyword → endpoint is the issue")
    print("  If rcdType=1/2 total >> rcdType=7 total → rcdType is the issue")
    print("  If all totals ≈ same → the API cap is real regardless of endpoint")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
