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
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{API_BASE}/categories?source_site=offertoday")
        for ct in r.json().get("categories", []):
            cat_names[ct["id"]] = ct["name"]

async def crawl_category(cat_id, depth, sem):
    async with sem:
        async with httpx.AsyncClient(timeout=120.0) as c:
            resp = await c.post(f"{API_BASE}/crawl-jobs", json={
                "source_site": "offertoday", "crawl_phase": "listing",
                "crawl_mode": "headless", "max_pages": depth,
                "category_ids": [cat_id],
            }, timeout=30.0)
            if resp.status_code not in (200, 201, 202):
                return {"cat_id": cat_id, "status": "api_error", "error": f"HTTP {resp.status_code}"}
            job_id = resp.json()["id"]
            for _ in range(100):
                await asyncio.sleep(3)
                r2 = await c.get(f"{API_BASE}/crawl-jobs/{job_id}", timeout=15.0)
                sd = r2.json(); st = sd.get("status")
                if st in ("completed", "failed"):
                    m = sd.get("metrics") or {}
                    return {"cat_id": cat_id, "status": st, "pages": m.get("pages_processed", 0), "ids": m.get("job_ids_collected", 0), "staged": m.get("listings_staged", 0), "error": sd.get("error_message")}
            return {"cat_id": cat_id, "status": "timeout", "ids": 0, "pages": 0}
async def main():
    await get_cat_names()
    sem = asyncio.Semaphore(3)
    print("=" * 100); print(f"OFFERTODAY STRESS TEST - {len(ALL_CATEGORIES)} cats @ depth={DEFAULT_DEPTH}"); print("=" * 100)
    print(f"{'Cat':<8} {'Name':<36} {'Pages':<6} {'IDs':<6} {'Status'}")
    print("-" * 80)
    start = time.time()
    tasks = [crawl_category(cid, DEFAULT_DEPTH, sem) for cid in ALL_CATEGORIES]
    results = await asyncio.gather(*tasks)
    results.sort(key=lambda r: r["cat_id"])
    p=f=l=t=0;fv=[];lv=[]
    for r in results:
        c=r["cat_id"];n=cat_names.get(c,"Unknown")[:34];s=r["status"];ids=r.get("ids",0);pg=r.get("pages",0);e=r.get("error");t+=ids
        ok=s=="completed" and not e
        if ok and ids>=10: sp="PASS";p+=1
        elif ok and ids<10: sp=f"LOW({ids})";l+=1;lv.append(f"Cat {c}: {ids} IDs")
        else: sp=f"FAIL:{e or s[:15]}";f+=1;fv.append(f"Cat {c}: {e or s}")
        print(f"{c:<8} {n:<36} {pg:<6} {ids:<6} {sp}")
    print("-" * 80)
    print(f"PASS: {p} | LOW VOL: {l} | FAIL: {f} | Total IDs: {t} | Time: {time.time()-start:.0f}s")
    if fv: print(f"\nFAILURES:"); [print(f"  {x}") for x in fv]
    if lv: print(f"\nLOW VOLUME:"); [print(f"  {x}") for x in lv]
    sys.exit(1 if f else 0)
asyncio.run(main())
