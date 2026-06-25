"""Full pagination stress test for all 31 offertoday sectors at depth=30."""
import asyncio, json, sys, time
import httpx

API_BASE = "http://backend-api:8000/api/v1"

ALL_CATEGORIES = [
    101000, 102000, 103000, 104000, 105000, 106000, 107000, 108000, 109000,
    110000, 111000, 112000, 113000, 114000, 115000, 116000, 117000, 118000,
    119000, 120000, 121000, 122000, 123000, 124000, 125000, 126000, 127000,
    128000, 129000, 130000, 999000,
]
DEFAULT_DEPTH = 30

cat_names = {}

async def get_cat_names():
    global cat_names
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{API_BASE}/categories?source_site=offertoday")
            for ct in r.json().get("categories", []):
                cat_names[ct["id"]] = ct["name"]
    except Exception:
        pass

async def crawl_category(cat_id, depth, sem):
    async with sem:
        try:
            async with httpx.AsyncClient(timeout=120.0) as c:
                resp = await c.post(f"{API_BASE}/crawl-jobs", json={
                    "source_site": "offertoday",
                    "crawl_phase": "listing",
                    "crawl_mode": "headless",
                    "max_pages": depth,
                    "category_ids": [cat_id],
                }, timeout=30.0)
                if resp.status_code not in (200, 201, 202):
                    return {"cat_id": cat_id, "status": "api_error", "error": f"HTTP {resp.status_code}"}
                data = resp.json()
                job_id = data["id"]

                for _ in range(100):
                    await asyncio.sleep(3)
                    r2 = await c.get(f"{API_BASE}/crawl-jobs/{job_id}", timeout=15.0)
                    sd = r2.json()
                    st = sd.get("status")
                    if st in ("completed", "failed"):
                        m = sd.get("metrics") or {}
                        return {
                            "cat_id": cat_id, "status": st,
                            "pages": m.get("pages_processed", 0),
                            "ids": m.get("job_ids_collected", 0),
                            "staged": m.get("listings_staged", 0),
                            "error": sd.get("error_message"),
                        }
                return {"cat_id": cat_id, "status": "timeout", "ids": 0, "pages": 0, "error": "timeout"}
        except Exception as e:
            return {"cat_id": cat_id, "status": "exception", "error": str(e)}

async def main():
    await get_cat_names()
    sem = asyncio.Semaphore(3)
    print("=" * 100)
    print(f"OFFERTODAY PAGINATION STRESS TEST - {len(ALL_CATEGORIES)} categories @ depth={DEFAULT_DEPTH}")
    print("=" * 100)
    print()
    print(f"{'Cat':<8} {'Name':<36} {'Pages':<7} {'IDs':<6} {'Staged':<7} {'Status'}")
    print("-" * 100)
    start = time.time()
    tasks = [crawl_category(cid, DEFAULT_DEPTH, sem) for cid in ALL_CATEGORIES]
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - start
    passed = 0; failed = 0; low_vol = 0; total_ids = 0; failures = []; low_vol_cats = []
    results.sort(key=lambda r: r["cat_id"])
    for r in results:
        cid = r["cat_id"]; name = cat_names.get(cid, "Unknown")[:34]
        status = r["status"]; ids = r.get("ids", 0); pages = r.get("pages", 0)
        staged = r.get("staged", 0); err = r.get("error"); total_ids += ids
        ok = (status == "completed" and not err)
        if ok and ids >= 10:
            status_label = "PASS"; passed += 1
        elif ok and ids < 10:
            status_label = f"LOW({ids}ids)"; low_vol += 1
            low_vol_cats.append(f"Cat {cid} ({name[:20]}): {ids} IDs")
        else:
            status_label = f"FAIL:{err or status[:15]}"; failed += 1
            failures.append(f"Cat {cid} ({name[:20]}): {err or status}")
        print(f"{cid:<8} {name:<36} {pages:<7} {ids:<6} {staged:<7} {status_label}")
    print("-" * 100)
    print(f"Total: {len(results)} | PASS (>=10 IDs): {passed} | LOW VOL: {low_vol} | FAIL: {failed}")
    print(f"Total unique IDs: {total_ids}")
    print(f"Runtime: {elapsed:.1f}s")
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures: print(f"  - {f}")
    if low_vol_cats:
        print(f"\nLOW VOLUME ({len(low_vol_cats)}):")
        for f in low_vol_cats: print(f"  - {f}")
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    asyncio.run(main())
