from __future__ import annotations

from urllib.parse import urlencode


JOBSDB_LISTING_API_URL = "https://hk.jobsdb.com/api/jobsearch/v5/search"
JOBSDB_LISTING_PAGE_SIZE = 32


def build_jobsdb_search_params(
    classification_id: int | str,
    *,
    page: int = 1,
    page_size: int = JOBSDB_LISTING_PAGE_SIZE,
) -> dict[str, int | str]:
    """Build the one authoritative JobsDB listing constraint."""

    try:
        native_id = int(classification_id)
        normalized_page = int(page)
        normalized_page_size = int(page_size)
    except (TypeError, ValueError) as exc:
        raise ValueError("JobsDB classification, page, and page size must be integers") from exc
    if native_id <= 0 or normalized_page <= 0 or normalized_page_size <= 0:
        raise ValueError("JobsDB classification, page, and page size must be positive")
    return {
        "siteKey": "HK-Main",
        "sourcesystem": "houston",
        "classification": native_id,
        "pageSize": normalized_page_size,
        "page": normalized_page,
        "locale": "en-HK",
        "sortmode": "ListedDate",
    }


def build_jobsdb_search_url(
    classification_id: int | str,
    *,
    page: int = 1,
    page_size: int = JOBSDB_LISTING_PAGE_SIZE,
) -> str:
    return (
        f"{JOBSDB_LISTING_API_URL}?"
        f"{urlencode(build_jobsdb_search_params(classification_id, page=page, page_size=page_size))}"
    )
