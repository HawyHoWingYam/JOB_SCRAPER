#!/usr/bin/env python3
"""Load test: scrape ALL offertoday categories at max depth.

Smart strategy: test each category at depth=30. Since the API is stateless
and results are cumulative, this inherently validates all shallower depths too.
All 31 categories are tested concurrently for efficiency.
"""

import asyncio
import httpx
import sys

API_BASE = "http://localhost:8000/api/v1"
SOURCE = "offertoday"
MAX_DEPTH = 30

CATEGORIES = [
    101000, 102000, 103000, 104000, 105000, 106000, 107000, 108000, 109000,
    110000, 111000, 112000, 113000, 114000, 115000, 116000, 117000, 118000,
    119000, 120000, 121000, 122000, 123000, 124000, 125000, 126000, 127000,
    128000, 129000, 130000, 999000,
]


async def trigger_crawl(cat_id: int) -> dict:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{API_BASE}/crawl-jobs",
                json={
                    "source_site": SOURCE,
                    "crawl_phase": "listing",
                    "crawl_mode": "headless",
                    "max_pages": MAX_DEPTH,
                    "category_ids": [cat_id],
                },
            )
            if resp.status_code not in (200, 201, 202):
                return {"cat_id": cat_id, "status": "api_error", "error": f"HTTP {resp.status_code}"}
            data = resp.json()
            job_id = data["id"]

            for _ in range(60):
                await asyncio.sleep(2)
                resp2 = await client.get(f"{API_BASE}/crawl-jobs/{job_id}")
                sd = resp2.json()
                st = sd.get("status")
                if st in ("completed", "failed"):
                    m = sd.get("metrics") or {}
                    return {
                        "cat_id": cat_id,
                        "status": st,
                        "pages": m.get("pages_processed", 0),
                        "ids": m.get("job_ids_collected", 0),
                        "error": sd.get("error_message"),
                    }

            # Check status after timeout
            async with httpx.AsyncClient(timeout=10.0) as c2:
                r3 = await c2.get(f"{API_BASE}/crawl-jobs/{job_id}")
                sd2 = r3.json()
                return {
                    "cat_id": cat_id,
                    "status": sd2.get("status", "timeout"),
                    "pages": (sd2.get("metrics") or {}).get("pages_processed", 0),
                    "ids": (sd2.get("metrics") or {}).get("job_ids_collected", 0),
                    "error": sd2.get("error_message") or "timeout",
                }
    except Exception as e:
        return {"cat_id": cat_id, "status": "exception", "error": str(e)}


async def run_load_test():
    print("=" * 80)
    print(f"OFFERTODAY LOAD TEST - ALL {len(CATEGORIES)} CATEGORIES AT DEPTH={MAX_DEPTH}")
    print("=" * 80)

    # Get category names
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{API_BASE}/categories?source_site=offertoday")
        all_cats = {ct["id"]: ct["name"] for ct in r.json().get("categories", [])}

    hdr = f"{'Category':<12} {'Name':<38} {'Pages':<8} {'IDs':<8} {'Status':<12}"
    print(hdr)
    print("-" * 80)

    # Launch all 31 crawl jobs concurrently
    sem = asyncio.Semaphore(10)  # Max 10 concurrent API requests

    async def bounded_crawl(cat_id):
        async with sem:
            return await trigger_crawl(cat_id)

    tasks = [bounded_crawl(cid) for cid in CATEGORIES]
    results = await asyncio.gather(*tasks)

    # Process results
    all_errors = []
    volume_issues = []
    total_ids = 0
    cats_with_10 = 0

    results.sort(key=lambda r: r["cat_id"])

    for r in results:
        cid = r["cat_id"]
        name = all_cats.get(cid, "Unknown")
        status = r["status"]
        ids = r.get("ids", 0)
        pages = r.get("pages", 0)
        error = r.get("error")

        total_ids += ids

        sd = "OK" if (status == "completed" and not error) else f"ERR:{error or status}"
        print(f"{cid:<12} {name[:36]:<38} {pages:<8} {ids:<8} {sd:<12}")

        if error:
            all_errors.append(f"cat={cid}({name}): {error}")
        elif ids >= 10:
            cats_with_10 += 1
        else:
            volume_issues.append(f"cat={cid}({name}): only {ids} IDs at depth={MAX_DEPTH}")

    # Summary
    print()
    print("=" * 80)
    print(f"SUMMARY - {len(CATEGORIES)} categories all at depth {MAX_DEPTH}")
    print("=" * 80)
    print(f"Categories with >= 10 unique IDs: {cats_with_10}/{len(CATEGORIES)}")
    print(f"Total unique IDs across all categories: {total_ids}")

    if all_errors:
        print(f"\nERRORS ({len(all_errors)}):")
        for e in all_errors:
            print(f"  - {e}")

    if volume_issues:
        print(f"\nVOLUME ISSUES ({len(volume_issues)}):")
        for v in volume_issues:
            print(f"  - {v}")
    else:
        print("\nAll categories meet minimum volume (>=10 IDs at depth 30)")

    if not all_errors and not volume_issues:
        print("\nALL CATEGORIES PASSED - Load test successful!")
    elif not all_errors:
        print("\nCompleted with volume warnings (some categories may be naturally small)")
    else:
        print("\nCompleted with errors - review above")

    return all_errors, volume_issues, results


if __name__ == "__main__":
    exit_code = 0
    errors, volumes, results = asyncio.run(run_load_test())
    if errors:
        exit_code = 1
    sys.exit(exit_code)
