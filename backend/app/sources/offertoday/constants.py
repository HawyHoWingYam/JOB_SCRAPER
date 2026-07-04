"""Shared OfferToday constants — canonical source of truth for headers, URLs, etc."""

from __future__ import annotations

from typing import Any

OFFERTODAY_BASE_URL = "https://www.offertoday.com"

# Two listing endpoints:
# search/list — recommendation-filtered (rcdType:7); returns ~600–700 IT jobs
# list        — category browse; may return the full unfiltered job database
OFFERTODAY_LISTING_SEARCH_URL = f"{OFFERTODAY_BASE_URL}/wapi/geek/recommend/search/list"
OFFERTODAY_LISTING_BROWSE_URL = f"{OFFERTODAY_BASE_URL}/wapi/geek/recommend/list"

OFFERTODAY_COMMON_HEADERS: dict[str, str] = {
    "api-language": "zh_HK",
    "x-requested-with": "XMLHttpRequest",
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json;charset=UTF-8",
}


def build_offertoday_listing_payload(
    *,
    category_id: int | None,
    keyword: str,
    page: int,
) -> dict[str, Any]:
    """Build the canonical OfferToday listing/search API payload."""
    payload: dict[str, Any] = {
        "keyword": keyword,
        "rcdType": 7,
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
