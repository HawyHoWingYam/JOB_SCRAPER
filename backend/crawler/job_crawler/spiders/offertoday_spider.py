"""OfferToday spider for crawling jobs via their REST API.

Offertoday uses a REST API behind Alibaba Cloud WAF that performs
TLS fingerprinting. httpx requests are blocked even with valid cookies.
Solution: route API calls through Playwright's Chromium browser, whose
TLS fingerprint is trusted by the WAF.

Key design:
- One shared Playwright browser page per crawl to maintain session/cookies
- API calls made via page.evaluate(fetch()) inside the browser context
- Fallback to listing-only data when WAF blocks detail calls

Listing crawl strategy (maximum coverage):
- Uses the search API (rcdType=7) with single-letter keyword probes.
  OfferToday's API returns only a subset when keyword="" but full results
  when a search term is used. We use a-z, 0-9 as keywords to cover all jobs.
- Progressively scans each keyword until no new jobs are found.
- Global dedup across all keywords ensures each job ID is collected once.
- When publish_time_window is set, it's applied per keyword probe.
"""

from __future__ import annotations

import asyncio
import json
import logging

from playwright.async_api import async_playwright

from app.crawl_phases import resolve_crawl_phase
from app.sources.contracts import CanonicalScrapedJob, build_offertoday_canonical_job
from app.sources.offertoday.parsers import (
    parse_offertoday_listing_response,
    extract_encrypted_job_id,
)
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

OFFERTODAY_BASE_URL = "https://www.offertoday.com"

MAX_PAGES_PER_KEYWORD = 50  # pages per keyword probe
MAX_PAGES = 2000  # overall safety cap

# Keyword probes to cover the full dataset.
# OfferToday search API returns different subsets per keyword.
# a-z + 0-9 covers all jobs when combined with dedup.
_KEYWORD_PROBES = [chr(c) for c in range(ord('a'), ord('z') + 1)] + [str(d) for d in range(10)]

# Detail phase tuning for WAF bypass
DETAIL_DELAY_SECONDS = 1.5
DETAIL_RETRY_MAX = 4
DETAIL_RETRY_BACKOFF_BASE = 2.0

_JS_FETCH_POST_URL = "https://www.offertoday.com/wapi/geek/recommend/search/list"

# JS snippet to POST a JSON payload to the search API.
# Takes a single 'payload' argument - the dict to send.
# Uses no Python string templating to avoid brace conflicts.
_JS_FETCH_POST_FN = """(payload) => {
  return fetch('""" + _JS_FETCH_POST_URL + """', {
    method: 'POST',
    headers: {
      'api-language': 'zh_HK',
      'x-requested-with': 'XMLHttpRequest',
      'accept': 'application/json, text/plain, */*',
      'content-type': 'application/json;charset=UTF-8',
    },
    body: JSON.stringify(payload)
  }).then(r => r.json());
}"""

_JS_FETCH_GET_URL_TEMPLATE = "https://www.offertoday.com/wapi/geek/recommend/jobDetail?id=%s&encryptJobId=%s"

# JS snippet to GET a URL. No arguments - URL is embedded.
_JS_FETCH_GET_FN = """() => {
  return fetch('%s').then(r => r.json());
}"""


def _build_search_payload(page: int, category_ids: list[int], keyword: str = "", publish_time: str = "") -> dict:
    """Build the search API payload with keyword probing for full coverage."""
    return {
        "keyword": keyword,
        "salaryType": 0,
        "employmentTypes": [],
        "publishTime": publish_time,
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


def build_canonical_job(parsed_job: dict) -> CanonicalScrapedJob:
    return build_offertoday_canonical_job(parsed_job)


class OfferTodaySpider:
    source_site = "offertoday"

    async def crawl(
        self,
        *,
        crawl_job_id: str,
        request_payload: dict,
        emit_page_processed,
        emit_detail_progress=None,
        emit_item_emitted,
        emit_listing_emitted=None,
        mark_detail_running=None,
        mark_detail_completed=None,
        mark_detail_failed=None,
    ):
        crawl_phase = resolve_crawl_phase(request_payload.get("crawl_phase"))
        crawl_mode = str(request_payload.get("crawl_mode") or "headless").strip().lower()
        is_headed = crawl_mode == "headed"
        global_max_pages = min(
            int(request_payload.get("max_pages") or 1000),
            MAX_PAGES,
        )
        pages_processed = 0
        items_emitted = 0
        listing_rank = 0

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=not is_headed,
                slow_mo=100 if is_headed else None,
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/149.0.0.0 Safari/537.36"
                ),
                locale="zh-HK",
            )
            page = await context.new_page()

            # Warm up: navigate to the search page to establish a WAF session
            try:
                await page.goto(
                    f"{OFFERTODAY_BASE_URL}/hk/search",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await asyncio.sleep(2.0)
            except Exception as exc:
                logger.warning("offertoday warmup navigation failed: %s", exc)

            if crawl_phase == "listing":
                result = await self._listing_phase(
                    page=page,
                    global_max_pages=global_max_pages,
                    request_payload=request_payload,
                    emit_page_processed=emit_page_processed,
                    emit_listing_emitted=emit_listing_emitted,
                    listing_rank=listing_rank,
                )
                pages_processed = result["pages_processed"]
                items_emitted = result["items_emitted"]
            else:
                result = await self._detail_phase(
                    page=page,
                    request_payload=request_payload,
                    emit_item_emitted=emit_item_emitted,
                    mark_detail_running=mark_detail_running,
                    mark_detail_completed=mark_detail_completed,
                    mark_detail_failed=mark_detail_failed,
                )
                pages_processed = result["pages_processed"]
                items_emitted = result["items_emitted"]

            await browser.close()

        return {"pages_processed": pages_processed, "items_emitted": items_emitted}

    async def _listing_phase(
        self,
        *,
        page,
        global_max_pages: int,
        request_payload: dict,
        emit_page_processed,
        emit_listing_emitted,
        listing_rank: int,
    ) -> dict:
        pages_processed = 0
        items_emitted = 0
        seen_job_ids: set[str] = set()
        category_ids = list(request_payload.get("category_ids") or [])
        explicit_window = request_payload.get("publish_time_window") or request_payload.get("publishTime") or ""

        for cat_id in category_ids:
            cat_code = int(cat_id) if not isinstance(cat_id, int) else cat_id

            for keyword in _KEYWORD_PROBES:
                if pages_processed >= global_max_pages:
                    logger.info("reached global max_pages=%d, stopping keyword loop", global_max_pages)
                    break

                consecutive_empty_pages = 0
                consecutive_no_new_pages = 0
                keyword_new_jobs = 0

                for page_num in range(1, MAX_PAGES_PER_KEYWORD + 1):
                    if pages_processed >= global_max_pages:
                        break

                    payload_body = _build_search_payload(
                        page_num, [cat_code],
                        keyword=keyword,
                        publish_time=explicit_window,
                    )
                    error = None

                    try:
                        data = await page.evaluate(_JS_FETCH_POST_FN, payload_body)
                    except Exception as exc:
                        error = str(exc)
                        data = None

                    if data is None or data.get("code") != 0:
                        msg = error or (data or {}).get("msg", "unknown error")
                        if emit_page_processed is not None:
                            emit_page_processed({
                                "phase": 1, "current_page": page_num,
                                "total_pages": MAX_PAGES_PER_KEYWORD,
                                "category_id": cat_code,
                                "keyword": keyword,
                                "error": msg,
                                "updated_at": utc_now().isoformat(),
                            })
                        consecutive_empty_pages += 1
                        if consecutive_empty_pages >= 2:
                            break
                        continue

                    consecutive_empty_pages = 0
                    parsed_jobs = parse_offertoday_listing_response(data)
                    if not parsed_jobs:
                        break

                    new_items_for_page = 0
                    for job in parsed_jobs:
                        encrypted_id = str(job.get("encrypted_job_id") or "").strip()
                        if not encrypted_id or encrypted_id in seen_job_ids:
                            continue
                        seen_job_ids.add(encrypted_id)
                        new_items_for_page += 1
                        keyword_new_jobs += 1

                        source_classification_name = ""
                        source_classification_id = str(job.get("job_function_code") or "")
                        if not source_classification_id:
                            jf = job.get("job_functions") or []
                            if jf:
                                source_classification_id = str(jf[0].get("code") or "")
                                source_classification_name = str(jf[0].get("name") or "")

                        if emit_listing_emitted is not None:
                            emit_listing_emitted({
                                "source_site": "offertoday",
                                "source_job_id": encrypted_id,
                                "source_url": f"{OFFERTODAY_BASE_URL}/hk/job/{encrypted_id}",
                                "source_classification_id": source_classification_id or None,
                                "source_classification_name": source_classification_name or None,
                                "listing_page": page_num,
                                "listing_rank": listing_rank,
                                "listing_payload": dict(job),
                            })

                    pages_processed += 1
                    if emit_page_processed is not None:
                        emit_page_processed({
                            "phase": 1, "current_page": page_num,
                            "total_pages": MAX_PAGES_PER_KEYWORD,
                            "category_id": cat_code,
                            "keyword": keyword,
                            "job_ids_collected": len(seen_job_ids),
                            "new_items_this_page": new_items_for_page,
                            "publish_time_window": explicit_window or "all",
                            "updated_at": utc_now().isoformat(),
                        })

                    if new_items_for_page <= 0:
                        consecutive_no_new_pages += 1
                        if consecutive_no_new_pages >= 10:
                            break
                    else:
                        consecutive_no_new_pages = 0

                    # Small delay between pages to be polite to the API
                    await asyncio.sleep(0.5)

                logger.info(
                    "keyword=%s category=%s added %d new jobs (total_seen=%d, pages=%d)",
                    keyword, cat_code, keyword_new_jobs, len(seen_job_ids), pages_processed,
                )

                # If a keyword probe found zero new pages (all empty), it means
                # we've exhausted potential new content. But different keywords
                # return overlapping subsets so we keep going through all probes.

        return {"pages_processed": pages_processed, "items_emitted": items_emitted}

    async def _detail_phase(
        self,
        *,
        page,
        request_payload: dict,
        emit_item_emitted,
        mark_detail_running=None,
        mark_detail_completed=None,
        mark_detail_failed=None,
    ) -> dict:
        detail_targets = list(request_payload.get("detail_targets") or [])
        if not detail_targets:
            return {"pages_processed": 0, "items_emitted": 0}

        pages_processed = 0
        items_emitted = 0
        total = len(detail_targets)

        for index, target in enumerate(detail_targets, start=1):
            encrypted_id = str(target.get("source_job_id") or "").strip()
            listing_job = dict(target.get("listing_payload") or {})
            if not encrypted_id:
                continue
            if mark_detail_running is not None:
                mark_detail_running(target)

            # Paced delay
            if index > 1:
                await asyncio.sleep(DETAIL_DELAY_SECONDS)

            detail_success = False
            for attempt in range(1, DETAIL_RETRY_MAX + 1):
                try:
                    js_url = _JS_FETCH_GET_URL_TEMPLATE % (encrypted_id, encrypted_id)
                    js_fn = _JS_FETCH_GET_FN % js_url
                    data = await page.evaluate(js_fn)
                except Exception as exc:
                    if attempt < DETAIL_RETRY_MAX:
                        backoff = DETAIL_RETRY_BACKOFF_BASE ** attempt
                        await asyncio.sleep(backoff)
                        continue
                    if mark_detail_failed is not None:
                        mark_detail_failed(target, str(exc))
                    break

                if data is not None and data.get("code") == 0:
                    detail_data = data.get("data") or {}
                    item = build_canonical_job({
                        **listing_job,
                        "description_html": str(detail_data.get("jobDesc") or "").strip(),
                        "description_text": str(detail_data.get("jobDesc") or "").strip(),
                    })

                    if emit_item_emitted is not None:
                        emit_item_emitted({
                            "listing_id": target.get("listing_id"),
                            "source_listing_crawl_job_id": target.get("source_listing_crawl_job_id"),
                            "job": item.to_dict(),
                        })
                    items_emitted += 1
                    if mark_detail_completed is not None:
                        mark_detail_completed(target, {
                            "canonical_job": item.to_dict(),
                            "listing_payload": dict(listing_job),
                        })
                    detail_success = True
                    break
                else:
                    msg = (data or {}).get("msg", "unknown error") if data else "no data"
                    if attempt < DETAIL_RETRY_MAX:
                        backoff = DETAIL_RETRY_BACKOFF_BASE ** attempt
                        await asyncio.sleep(backoff)
                        continue
                    if mark_detail_failed is not None:
                        mark_detail_failed(target, msg)
                    break

            if not detail_success:
                # Graceful fallback: build canonical job from listing data
                item = build_canonical_job(listing_job)
                if emit_item_emitted is not None:
                    emit_item_emitted({
                        "listing_id": target.get("listing_id"),
                        "source_listing_crawl_job_id": target.get("source_listing_crawl_job_id"),
                        "job": item.to_dict(),
                    })
                items_emitted += 1
                if mark_detail_completed is not None:
                    mark_detail_completed(target, {
                        "canonical_job": item.to_dict(),
                        "listing_payload": dict(listing_job),
                    })
                await asyncio.sleep(0.5)

        return {"pages_processed": pages_processed, "items_emitted": items_emitted}
