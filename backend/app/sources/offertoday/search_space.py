"""OfferToday search-space helpers.

These helpers keep the backend crawl aligned with how OfferToday actually
indexes jobs:

- category 118000 is the IT family root
- the IT family has multiple leaf categories that should be crawled
  independently for broader coverage
- keyword probes are optional and should be paginated per search condition,
  not as one global task budget
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

DEFAULT_OFFERTODAY_IT_KEYWORDS: tuple[str, ...] = (
    "IT",
    "software",
    "data",
    "support",
    "project",
    "security",
    "network",
    "web",
    "testing",
    "developer",
    "business analyst",
    "telecommunications",
    "ERP",
    "Dynamics",
    "SAP",
    "consultant",
    "architect",
    "programmer",
    "Python",
    "iOS",
    "Android",
    "AWS",
    "Azure",
    "AI",
    "machine learning",
    "database",
    "frontend",
    "backend",
    "full stack",
    "system",
    "infrastructure",
    "QA",
    "UX",
    "UI",
    "blockchain",
    "cybersecurity",
)

DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS: tuple[str, ...] = (
    "network engineer",
    "engineer",
    "devops",
    "software engineer",
    "cloud",
    "analyst",
)

OFFERTODAY_IT_CATEGORY_CODES: tuple[int, ...] = (
    118000,
    118001,
    118002,
    118003,
    118004,
    118005,
    118006,
    118007,
    118008,
    118009,
    118010,
    118011,
    118012,
    118013,
    118014,
    118015,
    118016,
    118017,
    118018,
    118019,
    118020,
    118021,
    118999,
)
_OFFERTODAY_IT_CATEGORY_SET = set(OFFERTODAY_IT_CATEGORY_CODES)


def _normalize_category_ids(category_ids: Sequence[int] | None) -> list[int]:
    input_ids = []
    seen: set[int] = set()
    for category_id in category_ids or []:
        if not str(category_id).strip():
            continue
        resolved_category_id = int(category_id)
        if resolved_category_id in seen:
            continue
        input_ids.append(resolved_category_id)
        seen.add(resolved_category_id)
    return input_ids


def normalize_offertoday_keywords(keywords: str | Sequence[str] | None) -> list[str]:
    """Normalize a comma-separated keyword string or a sequence of strings."""
    if keywords is None:
        return []

    if isinstance(keywords, str):
        candidates: Iterable[str] = keywords.split(",")
    else:
        candidates = keywords

    normalized: list[str] = []
    seen: set[str] = set()
    for keyword in candidates:
        cleaned = str(keyword or "").strip()
        if not cleaned or cleaned in seen:
            continue
        normalized.append(cleaned)
        seen.add(cleaned)
    return normalized


def expand_offertoday_category_ids(
    category_ids: Sequence[int] | None,
    *,
    default_to_it: bool = True,
) -> list[int]:
    """Expand the category search scope to the full IT family when requested."""
    input_ids = _normalize_category_ids(category_ids)
    if not input_ids:
        return list(OFFERTODAY_IT_CATEGORY_CODES) if default_to_it else []

    expanded: list[int] = []
    seen: set[int] = set()
    for category_id in input_ids:
        category_group = OFFERTODAY_IT_CATEGORY_CODES if category_id == 118000 else (category_id,)
        for resolved_category_id in category_group:
            if resolved_category_id in seen:
                continue
            expanded.append(resolved_category_id)
            seen.add(resolved_category_id)
    return expanded


def _should_include_default_it_keyword_pack(
    *,
    category_ids: Sequence[int] | None,
    default_to_it: bool,
) -> bool:
    if not default_to_it:
        return False

    normalized_category_ids = _normalize_category_ids(category_ids)
    if not normalized_category_ids:
        return True

    return any(category_id in _OFFERTODAY_IT_CATEGORY_SET for category_id in normalized_category_ids)


def build_offertoday_listing_queries(
    category_ids: Sequence[int] | None,
    *,
    keywords: str | Sequence[str] | None = None,
    max_pages_per_query: int = 100,
    default_to_it: bool = True,
) -> list[dict[str, Any]]:
    """Build the cartesian listing query plan.

    Each query plan is a simple dict with the category code, keyword and page.
    Pagination is intentionally scoped per query so completeness is not capped
    by a global task budget.
    """
    if max_pages_per_query < 1:
        raise ValueError("max_pages_per_query must be >= 1")

    normalized_category_ids = _normalize_category_ids(category_ids)
    expanded_categories = expand_offertoday_category_ids(
        normalized_category_ids,
        default_to_it=default_to_it,
    )
    plans: list[dict[str, Any]] = []

    explicit_keywords = normalize_offertoday_keywords(keywords)
    if explicit_keywords:
        for keyword in explicit_keywords:
            for page in range(1, max_pages_per_query + 1):
                plans.append(
                    {
                        "search_family": "explicit_keyword",
                        "category_id": None,
                        "keyword": keyword,
                        "page": page,
                    }
                )
        return plans

    for category_id in expanded_categories:
        search_family = (
            "it_category" if category_id in _OFFERTODAY_IT_CATEGORY_SET else "category_search"
        )
        for page in range(1, max_pages_per_query + 1):
            plans.append(
                {
                    "search_family": search_family,
                    "category_id": category_id,
                    "keyword": "",
                    "page": page,
                    "endpoint": "browse",
                }
            )

    if _should_include_default_it_keyword_pack(
        category_ids=normalized_category_ids,
        default_to_it=default_to_it,
    ):
        for keyword in DEFAULT_OFFERTODAY_IT_KEYWORDS:
            for page in range(1, max_pages_per_query + 1):
                plans.append(
                    {
                        "search_family": "it_keyword",
                        "category_id": None,
                        "keyword": keyword,
                        "page": page,
                    }
                )

    if _should_include_default_it_keyword_pack(
        category_ids=normalized_category_ids,
        default_to_it=default_to_it,
    ):
        for keyword in DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS:
            for page in range(1, max_pages_per_query + 1):
                plans.append(
                    {
                        "search_family": "it_hybrid",
                        "category_id": 118000,
                        "keyword": keyword,
                        "page": page,
                    }
                )
    return plans
