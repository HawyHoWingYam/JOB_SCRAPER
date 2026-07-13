"""Shared OfferToday constants — canonical source of truth for headers, URLs, etc."""

from __future__ import annotations

from typing import Any

from app.sources.offertoday.listing_contract import (
    OFFERTODAY_LISTING_BROWSE_CONTRACT_URL,
    OFFERTODAY_LISTING_SEARCH_CONTRACT_URL,
    OfferTodayListingCursor,
)

OFFERTODAY_BASE_URL = "https://www.offertoday.com"

# Two listing endpoints:
# search/list — recommendation-filtered (rcdType:7); returns ~600–700 IT jobs
# list        — category browse; may return the full unfiltered job database
OFFERTODAY_LISTING_SEARCH_URL = OFFERTODAY_LISTING_SEARCH_CONTRACT_URL
OFFERTODAY_LISTING_BROWSE_URL = OFFERTODAY_LISTING_BROWSE_CONTRACT_URL

OFFERTODAY_COMMON_HEADERS: dict[str, str] = {
    "api-language": "zh_HK",
    "x-requested-with": "XMLHttpRequest",
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json;charset=UTF-8",
}


def _validate_offertoday_rcd_type(rcd_type: Any) -> None:
    if rcd_type is not None and type(rcd_type) is not int:
        raise ValueError("rcd_type must be an int or None")


def build_offertoday_listing_payload(
    *,
    category_id: int | None,
    keyword: str,
    page: int,
    rcd_type: int | None = 7,
    page_size: int = 50,
    cursor: OfferTodayListingCursor | None = None,
) -> dict[str, Any]:
    """Build the canonical OfferToday listing/search API payload."""
    _validate_offertoday_rcd_type(rcd_type)
    if type(page_size) is not int or page_size < 1:
        raise ValueError("page_size must be a positive exact integer")
    if type(page) is not int or page < 1:
        raise ValueError("page must be a positive exact integer")
    payload: dict[str, Any] = {
        "keyword": keyword,
    }
    if rcd_type is not None:
        payload["rcdType"] = rcd_type
    payload.update(
        {
            "pageSize": page_size,
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
    )
    if category_id is not None:
        payload["jobFunctionCodes"] = [category_id]
    if cursor is not None:
        payload.update(cursor.to_request_fields())
    return payload
