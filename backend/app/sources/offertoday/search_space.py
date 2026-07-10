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
from typing import Any, Literal

from app.scraper.offertoday.category_registry import OFFERTODAY_CATEGORIES_L1
from app.sources.offertoday.listing_runner import OfferTodayListingCondition

DEFAULT_OFFERTODAY_IT_KEYWORDS: tuple[str, ...] = (
    # --- 通用 ---
    "IT",
    "software",
    "system",
    "web",
    "API",
    "microservice",
    "automation",
    "Linux",
    "platform",
    "Agile",
    # --- Cloud / Infrastructure ---
    "AWS",
    "Azure",
    "GCP",
    "Google Cloud",
    "Kubernetes",
    "Docker",
    "Terraform",
    "Ansible",
    # --- DevOps / CI-CD ---
    "CI/CD",
    "Jenkins",
    "GitHub Actions",
    "GitLab",
    "SRE",
    "Site Reliability",
    "Helm",
    # --- 程式語言 ---
    "Python",
    "java",
    "javascript",
    "typescript",
    "C#",
    ".NET",
    "Go",
    "Rust",
    "Kotlin",
    "Swift",
    "C++",
    "PHP",
    "Ruby",
    "Scala",
    # --- 前端 / JS 生態 ---
    "React",
    "Angular",
    "Vue",
    "Node.js",
    "Next.js",
    # --- Mobile / Cross-Platform ---
    "iOS",
    "Android",
    "Flutter",
    "React Native",
    # --- 數據 / Database ---
    "data",
    "database",
    "SQL",
    "NoSQL",
    "MongoDB",
    "PostgreSQL",
    "MySQL",
    "Redis",
    "Big Data",
    "Spark",
    "Kafka",
    "Hadoop",
    "ETL",
    # --- AI / ML ---
    "AI",
    "machine learning",
    "Deep Learning",
    "NLP",
    "Computer Vision",
    "data science",
    "TensorFlow",
    "PyTorch",
    "LLM",
    "GenAI",
    # --- 安全 ---
    "security",
    "cybersecurity",
    "blockchain",
    "pentest",
    "penetration",
    "IAM",
    "SOC",
    "Zero Trust",
    # --- 角色 Titles ---
    "developer",
    "programmer",
    "architect",
    "consultant",
    "business analyst",
    "product manager",
    "product owner",
    "scrum master",
    "solution architect",
    "data engineer",
    "data scientist",
    # --- 測試 / QA ---
    "testing",
    "QA",
    # --- UX/UI ---
    "frontend",
    "backend",
    "full stack",
    "UX",
    "UI",
    # --- Domain ---
    "telecommunications",
    "ERP",
    "SAP",
    "Dynamics",
    "fintech",
    "IoT",
    "embedded",
    "firmware",
    # --- 其他 ---
    "support",
    "project",
    "network",
    "infrastructure",
    # --- 新興 ---
    "Web3",
    "AR",
    "VR",
    "quantum",
)

DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS: tuple[str, ...] = (
    "engineer",
    "devops",
    "cloud",
    "analyst",
    "developer",
    "specialist",
    "consultant",
    "administrator",
    "manager",
    "lead",
    "officer",
    "technician",
    "designer",
    "scientist",
    "operator",
    "coordinator",
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
        category_group = (
            OFFERTODAY_IT_CATEGORY_CODES if category_id == 118000 else (category_id,)
        )
        for resolved_category_id in category_group:
            if resolved_category_id in seen:
                continue
            expanded.append(resolved_category_id)
            seen.add(resolved_category_id)
    return expanded


def resolve_offertoday_detail_category_ids(
    category_ids: Sequence[int] | None,
    *,
    source_listing_crawl_job_id: str | None,
) -> list[int]:
    """Resolve detail scope without narrowing an already bounded listing run."""

    if source_listing_crawl_job_id is not None:
        return []
    return expand_offertoday_category_ids(category_ids, default_to_it=False)


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

    return any(
        category_id in _OFFERTODAY_IT_CATEGORY_SET
        for category_id in normalized_category_ids
    )


def build_offertoday_listing_conditions(
    category_ids: Sequence[int] | None,
    *,
    keywords: str | Sequence[str] | None = None,
    default_to_it: bool = True,
    endpoint: Literal["search", "browse"] = "search",
    rcd_type: int | None = 7,
) -> list[OfferTodayListingCondition]:
    """Build the ordered, page-independent OfferToday listing conditions."""
    normalized_category_ids = _normalize_category_ids(category_ids)
    explicit_keywords = normalize_offertoday_keywords(keywords)
    if explicit_keywords:
        return [
            OfferTodayListingCondition(
                search_family="explicit_keyword",
                category_id=None,
                keyword=keyword,
                endpoint=endpoint,
                rcd_type=rcd_type,
            )
            for keyword in explicit_keywords
        ]

    conditions = [
        OfferTodayListingCondition(
            search_family=(
                "it_category"
                if category_id in _OFFERTODAY_IT_CATEGORY_SET
                else "category_search"
            ),
            category_id=category_id,
            keyword="",
            endpoint="browse",
            rcd_type=rcd_type,
        )
        for category_id in expand_offertoday_category_ids(
            normalized_category_ids,
            default_to_it=default_to_it,
        )
    ]

    if not _should_include_default_it_keyword_pack(
        category_ids=normalized_category_ids,
        default_to_it=default_to_it,
    ):
        return conditions

    conditions.extend(
        OfferTodayListingCondition(
            search_family="it_keyword",
            category_id=None,
            keyword=keyword,
            endpoint=endpoint,
            rcd_type=rcd_type,
        )
        for keyword in DEFAULT_OFFERTODAY_IT_KEYWORDS
    )
    conditions.extend(
        OfferTodayListingCondition(
            search_family="it_hybrid",
            category_id=118000,
            keyword=keyword,
            endpoint=endpoint,
            rcd_type=rcd_type,
        )
        for keyword in DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS
    )
    return conditions


def build_offertoday_census_conditions(
    *,
    endpoint: Literal["search", "browse"],
    rcd_type: int | None,
) -> list[OfferTodayListingCondition]:
    """Build one census condition for each canonical top-level category."""
    return [
        OfferTodayListingCondition(
            search_family="census_category",
            category_id=category.code,
            keyword="",
            endpoint=endpoint,
            rcd_type=rcd_type,
        )
        for category in OFFERTODAY_CATEGORIES_L1
    ]


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

    conditions = build_offertoday_listing_conditions(
        category_ids,
        keywords=keywords,
        default_to_it=default_to_it,
    )
    plans: list[dict[str, Any]] = []
    for condition in conditions:
        for page in range(1, max_pages_per_query + 1):
            plan: dict[str, Any] = {
                "search_family": condition.search_family,
                "category_id": condition.category_id,
                "keyword": condition.keyword,
                "page": page,
            }
            if condition.search_family in {"it_category", "category_search"}:
                plan["endpoint"] = condition.endpoint
            plans.append(plan)
    return plans
