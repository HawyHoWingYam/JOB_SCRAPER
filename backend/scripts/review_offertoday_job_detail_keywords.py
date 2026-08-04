#!/usr/bin/env python3
"""Review OfferToday keyword coverage without mutating catalog or Job data."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import contextmanager
import csv
from dataclasses import dataclass, replace
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time
import unicodedata
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func, select, text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.crawl_job_listing import CrawlJobListing  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.offertoday_coverage import OfferTodayKeywordEntry  # noqa: E402
from app.models.source_classification import SourceClassification  # noqa: E402
from app.models.source_job_attributes import (  # noqa: E402
    JobSourceClassificationPath,
    JobSourceClassificationPathNode,
)
from app.scraper.offertoday_browser_runtime import (  # noqa: E402
    OfferTodayBrowserRuntime,
)
from app.services.offertoday_keyword_catalog import (  # noqa: E402
    OFFERTODAY_IT_CLASSIFICATION_ID,
    normalize_offertoday_keyword,
)
from app.services.offertoday_research_staging_service import (  # noqa: E402
    ResearchNoopListingStagingSink,
)
from app.sources.offertoday.listing_contract import (  # noqa: E402
    production_offertoday_listing_request_policy,
)
from app.sources.offertoday.listing_runner import (  # noqa: E402
    RESULT_TERMINAL_POLICY_ID,
    ListingConditionOutcome,
    ListingPageObservation,
    ListingRetryPolicy,
    ListingStopPolicy,
    OfferTodayListingCondition,
    OfferTodayListingRunner,
)
from app.utils.time import utc_now  # noqa: E402


SCHEMA_VERSION = 1
SOURCE_SITE = "offertoday"
DEFAULT_MIN_SUPPORT = 3
DEFAULT_EXAMPLE_LIMIT = 3
DEFAULT_STATEMENT_TIMEOUT_MS = 30_000
DEFAULT_PAGE_DELAY_SECONDS = 1.5
DEFAULT_REQUEST_CAP = 250
DEFAULT_MAX_ADDITIONS = 30
DEFAULT_MAX_RETIREMENTS = 30
MAX_EVIDENCE_IDS_PER_TARGET = 30
MAX_SNIPPET_LENGTH = 180
_ASCII_ALNUM = "0-9a-z"
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


@dataclass(frozen=True, slots=True)
class CandidateTerm:
    classification_id: str
    keyword: str
    family: str
    candidate_kind: str
    rationale: str


@dataclass(frozen=True, slots=True)
class JobEvidence:
    job_id: str
    source_job_id: str
    title: str
    description: str
    company_name: str
    posted_date: str | None
    paths: tuple[tuple[dict[str, Any], ...], ...]


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    key: str
    kind: str
    classification_id: str
    category_id: int
    keyword: str
    pages: int
    corpus_detail_matches: int = 0


class ProbeBudgetExceeded(RuntimeError):
    """Raised before a listing API request would exceed the approved cap."""


class ProbeRequestBudget:
    def __init__(self, cap: int) -> None:
        if cap < 1:
            raise ValueError("request cap must be positive")
        self.cap = cap
        self.started = 0

    def consume(self) -> None:
        if self.started >= self.cap:
            raise ProbeBudgetExceeded(
                f"OfferToday keyword review request cap reached ({self.cap})"
            )
        self.started += 1


class BudgetedListingTransport:
    def __init__(self, runtime: OfferTodayBrowserRuntime, budget: ProbeRequestBudget):
        self._runtime = runtime
        self._budget = budget

    @property
    def browser_context_hash(self) -> str | None:
        return self._runtime.browser_context_hash

    async def fetch_listing_page(self, payload, *, listing_url=None):
        self._budget.consume()
        return await self._runtime.fetch_listing_page(
            payload,
            listing_url=listing_url,
        )

    async def fetch_listing_json(self, payload, *, listing_url=None):
        result = await self.fetch_listing_page(payload, listing_url=listing_url)
        return result.payload

    async def restart_after_browser_loss(self) -> None:
        await self._runtime.restart_after_browser_loss()

    async def restart_after_stalled_query(self) -> None:
        await self._runtime.restart_after_stalled_query()


class MemoryObservationSink:
    def __init__(self) -> None:
        self.observations: list[ListingPageObservation] = []
        self.outcomes: list[ListingConditionOutcome] = []

    async def record_page_attempt(self, observation: ListingPageObservation) -> None:
        self.observations.append(observation)

    async def record_condition_outcome(self, outcome: ListingConditionOutcome) -> None:
        self.outcomes.append(outcome)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            default=_json_default,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported review schema in {path}")
    return payload


@contextmanager
def read_only_session(
    session_factory: Callable[[], Any] = SessionLocal,
    *,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
):
    """Yield one session whose PostgreSQL transaction is database-enforced read-only."""

    if statement_timeout_ms < 1:
        raise ValueError("statement timeout must be positive")
    db = session_factory()
    try:
        bind = db.get_bind()
        if bind.dialect.name != "postgresql":
            raise RuntimeError(
                "OfferToday keyword corpus review requires PostgreSQL read-only enforcement"
            )
        db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(
            text("SET LOCAL statement_timeout = :timeout"),
            {"timeout": f"{statement_timeout_ms}ms"},
        )
        yield db
    finally:
        db.rollback()
        db.close()


def normalize_corpus_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(normalized.split())


def title_language(title: str) -> str:
    has_cjk = bool(_CJK_PATTERN.search(title))
    has_latin = bool(re.search(r"[A-Za-z]", title))
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "zh"
    if has_latin:
        return "latin"
    return "other"


def term_pattern(keyword: str) -> re.Pattern[str]:
    normalized = normalize_corpus_text(keyword)
    if not normalized:
        raise ValueError("keyword cannot be empty")
    escaped = re.escape(normalized)
    if _CJK_PATTERN.search(normalized):
        return re.compile(escaped)
    return re.compile(rf"(?<![{_ASCII_ALNUM}]){escaped}(?![{_ASCII_ALNUM}])")


def matches_term(value: str, keyword: str) -> bool:
    return bool(term_pattern(keyword).search(normalize_corpus_text(value)))


def matched_snippet(value: str, keyword: str, *, limit: int = MAX_SNIPPET_LENGTH) -> str:
    normalized = " ".join(str(value or "").split())
    corpus = normalize_corpus_text(normalized)
    match = term_pattern(keyword).search(corpus)
    if match is None:
        return normalized[:limit]
    start = max(0, match.start() - limit // 3)
    end = min(len(normalized), start + limit)
    prefix = "…" if start else ""
    suffix = "…" if end < len(normalized) else ""
    return f"{prefix}{normalized[start:end]}{suffix}"


def load_candidate_terms(path: Path) -> tuple[CandidateTerm, ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {
            "classification_id",
            "keyword",
            "family",
            "candidate_kind",
            "rationale",
        }
        if not required.issubset(set(reader.fieldnames or ())):
            raise ValueError(f"Candidate CSV must contain {sorted(required)}")
        candidates: list[CandidateTerm] = []
        seen: set[tuple[str, str]] = set()
        for row_number, row in enumerate(reader, start=2):
            classification_id = str(row.get("classification_id") or "").strip()
            keyword = " ".join(str(row.get("keyword") or "").split())
            family = str(row.get("family") or "").strip()
            candidate_kind = str(row.get("candidate_kind") or "").strip()
            rationale = str(row.get("rationale") or "").strip()
            if not all((classification_id, keyword, family, candidate_kind, rationale)):
                raise ValueError(f"Candidate CSV row {row_number} has an empty field")
            identity = (classification_id, normalize_offertoday_keyword(keyword))
            if identity in seen:
                raise ValueError(f"Duplicate candidate identity on row {row_number}")
            seen.add(identity)
            candidates.append(
                CandidateTerm(
                    classification_id=classification_id,
                    keyword=keyword,
                    family=family,
                    candidate_kind=candidate_kind,
                    rationale=rationale,
                )
            )
    return tuple(candidates)


def _date_payload(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _load_jobs(db) -> tuple[JobEvidence, ...]:
    rows = db.execute(
        select(
            Job.id,
            Job.source_job_id,
            Job.title,
            Job.description,
            Job.posted_date,
            Company.name,
        )
        .join(Company, Company.id == Job.company_id)
        .where(
            Job.source_site == SOURCE_SITE,
            Job.is_deleted.is_(False),
            func.length(func.trim(Job.title)) > 0,
            func.length(func.trim(Job.description)) > 0,
        )
        .order_by(Job.source_job_id)
    ).all()

    path_rows = db.execute(
        select(
            JobSourceClassificationPath.job_id,
            JobSourceClassificationPath.source_order,
            JobSourceClassificationPath.is_primary,
            JobSourceClassificationPathNode.source_position,
            JobSourceClassificationPathNode.native_depth,
            JobSourceClassificationPathNode.source_classification_id,
            JobSourceClassificationPathNode.native_id,
            JobSourceClassificationPathNode.label,
        )
        .join(Job, Job.id == JobSourceClassificationPath.job_id)
        .join(
            JobSourceClassificationPathNode,
            JobSourceClassificationPathNode.path_id
            == JobSourceClassificationPath.id,
        )
        .where(
            Job.source_site == SOURCE_SITE,
            Job.is_deleted.is_(False),
        )
        .order_by(
            JobSourceClassificationPath.job_id,
            JobSourceClassificationPath.source_order,
            JobSourceClassificationPathNode.source_position,
        )
    ).all()

    paths_by_job: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in path_rows:
        paths_by_job[str(row.job_id)][int(row.source_order)].append(
            {
                "source_position": int(row.source_position),
                "native_depth": int(row.native_depth),
                "classification_id": str(row.source_classification_id),
                "native_id": str(row.native_id),
                "label": str(row.label),
                "is_primary": bool(row.is_primary),
            }
        )

    jobs: list[JobEvidence] = []
    for row in rows:
        job_paths = tuple(
            tuple(nodes)
            for _, nodes in sorted(paths_by_job.get(str(row.id), {}).items())
        )
        jobs.append(
            JobEvidence(
                job_id=str(row.id),
                source_job_id=str(row.source_job_id),
                title=str(row.title),
                description=str(row.description or ""),
                company_name=str(row.name),
                posted_date=_date_payload(row.posted_date),
                paths=job_paths,
            )
        )
    return tuple(jobs)


def _load_classifications(db) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            SourceClassification.id,
            SourceClassification.classification_id,
            SourceClassification.native_id,
            SourceClassification.label,
            SourceClassification.parent_id,
            SourceClassification.depth,
            SourceClassification.is_top_level,
            SourceClassification.is_active,
        )
        .where(SourceClassification.source_site == SOURCE_SITE)
        .order_by(
            SourceClassification.depth,
            SourceClassification.classification_id,
        )
    ).all()
    identity_by_row_id = {
        str(row.id): str(row.classification_id) for row in rows
    }
    return [
        {
            "classification_id": str(row.classification_id),
            "native_id": str(row.native_id),
            "label": str(row.label),
            "parent_classification_id": identity_by_row_id.get(str(row.parent_id)),
            "depth": int(row.depth),
            "is_top_level": bool(row.is_top_level),
            "is_active": bool(row.is_active),
        }
        for row in rows
    ]


def _load_keyword_entries(db) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            OfferTodayKeywordEntry.id,
            OfferTodayKeywordEntry.keyword,
            OfferTodayKeywordEntry.normalized_keyword,
            OfferTodayKeywordEntry.enabled,
            OfferTodayKeywordEntry.notes,
            OfferTodayKeywordEntry.last_new_job_ids,
            OfferTodayKeywordEntry.last_duplicate_rate,
            OfferTodayKeywordEntry.last_run_at,
            SourceClassification.classification_id,
            SourceClassification.label,
        )
        .join(
            SourceClassification,
            SourceClassification.id
            == OfferTodayKeywordEntry.source_classification_id,
        )
        .where(SourceClassification.source_site == SOURCE_SITE)
        .order_by(
            SourceClassification.classification_id,
            OfferTodayKeywordEntry.normalized_keyword,
        )
    ).all()
    return [
        {
            "entry_id": str(row.id),
            "classification_id": str(row.classification_id),
            "classification_label": str(row.label),
            "keyword": str(row.keyword),
            "normalized_keyword": str(row.normalized_keyword),
            "enabled": bool(row.enabled),
            "notes": str(row.notes or ""),
            "last_new_job_ids": row.last_new_job_ids,
            "last_duplicate_rate": row.last_duplicate_rate,
            "last_run_at": _date_payload(row.last_run_at),
        }
        for row in rows
    ]


def _load_staging_summary(db) -> dict[str, Any]:
    status_rows = db.execute(
        select(CrawlJobListing.detail_status, func.count())
        .where(CrawlJobListing.source_site == SOURCE_SITE)
        .group_by(CrawlJobListing.detail_status)
        .order_by(CrawlJobListing.detail_status)
    ).all()
    totals = db.execute(
        select(
            func.count(),
            func.count(func.distinct(CrawlJobListing.source_job_id)),
            func.min(CrawlJobListing.created_at),
            func.max(CrawlJobListing.created_at),
        ).where(CrawlJobListing.source_site == SOURCE_SITE)
    ).one()
    return {
        "rows": int(totals[0] or 0),
        "distinct_source_job_ids": int(totals[1] or 0),
        "created_at_min": _date_payload(totals[2]),
        "created_at_max": _date_payload(totals[3]),
        "detail_status_counts": {
            str(status): int(count) for status, count in status_rows
        },
    }


def _example_payload(job: JobEvidence, keyword: str) -> dict[str, Any]:
    title_match = matches_term(job.title, keyword)
    source = job.title if title_match else job.description
    return {
        "source_job_id": job.source_job_id,
        "title": job.title,
        "company_name": job.company_name,
        "posted_date": job.posted_date,
        "classification_paths": [list(path) for path in job.paths],
        "matched_field": "title" if title_match else "description",
        "snippet": matched_snippet(source, keyword),
    }


def _term_analysis(
    jobs: Sequence[JobEvidence],
    keyword: str,
    *,
    current_title_covered: set[str] | None = None,
    example_limit: int = DEFAULT_EXAMPLE_LIMIT,
) -> tuple[dict[str, Any], set[str], set[str]]:
    title_ids: set[str] = set()
    detail_ids: set[str] = set()
    matching_jobs: list[JobEvidence] = []
    for job in jobs:
        title_match = matches_term(job.title, keyword)
        detail_match = title_match or matches_term(job.description, keyword)
        if title_match:
            title_ids.add(job.source_job_id)
        if detail_match:
            detail_ids.add(job.source_job_id)
            matching_jobs.append(job)
    matching_jobs.sort(
        key=lambda item: (
            0 if item.source_job_id in title_ids else 1,
            item.posted_date or "",
            item.source_job_id,
        )
    )
    uncovered = (
        title_ids - current_title_covered
        if current_title_covered is not None
        else set()
    )
    return (
        {
            "title_match_count": len(title_ids),
            "detail_match_count": len(detail_ids),
            "uncovered_title_match_count": len(uncovered),
            "examples": [
                _example_payload(job, keyword)
                for job in matching_jobs[:example_limit]
            ],
        },
        title_ids,
        detail_ids,
    )


def build_corpus_snapshot(
    *,
    jobs: Sequence[JobEvidence],
    classifications: Sequence[Mapping[str, Any]],
    keyword_entries: Sequence[Mapping[str, Any]],
    candidates: Sequence[CandidateTerm],
    staging_summary: Mapping[str, Any],
    min_support: int = DEFAULT_MIN_SUPPORT,
    example_limit: int = DEFAULT_EXAMPLE_LIMIT,
    extracted_at: datetime | None = None,
) -> dict[str, Any]:
    if min_support < 1 or example_limit < 1:
        raise ValueError("min support and example limit must be positive")

    enabled_entries = [row for row in keyword_entries if row.get("enabled")]
    current_title_covered: set[str] = set()
    current_detail_covered: set[str] = set()
    keyword_results: list[dict[str, Any]] = []
    for entry in enabled_entries:
        analysis, title_ids, detail_ids = _term_analysis(
            jobs,
            str(entry["keyword"]),
            example_limit=example_limit,
        )
        current_title_covered.update(title_ids)
        current_detail_covered.update(detail_ids)
        keyword_results.append({**dict(entry), **analysis})

    disabled_entries = [row for row in keyword_entries if not row.get("enabled")]
    for entry in disabled_entries:
        analysis, _, _ = _term_analysis(
            jobs,
            str(entry["keyword"]),
            example_limit=example_limit,
        )
        keyword_results.append({**dict(entry), **analysis})
    keyword_results.sort(
        key=lambda row: (
            str(row["classification_id"]),
            str(row["normalized_keyword"]),
        )
    )

    current_identities = {
        (
            str(row["classification_id"]),
            str(row["normalized_keyword"]),
        )
        for row in keyword_entries
    }
    candidate_results: list[dict[str, Any]] = []
    for candidate in candidates:
        identity = (
            candidate.classification_id,
            normalize_offertoday_keyword(candidate.keyword),
        )
        analysis, _, _ = _term_analysis(
            jobs,
            candidate.keyword,
            current_title_covered=current_title_covered,
            example_limit=example_limit,
        )
        already_present = identity in current_identities
        supported = (
            int(analysis["detail_match_count"]) >= min_support
            and int(analysis["title_match_count"]) >= 2
        )
        if already_present:
            corpus_status = "already_present"
        elif not supported:
            corpus_status = "insufficient_support"
        elif candidate.candidate_kind == "language_variant":
            corpus_status = "variant_or_replacement"
        else:
            corpus_status = "probe_addition_candidate"
        candidate_results.append(
            {
                "classification_id": candidate.classification_id,
                "keyword": candidate.keyword,
                "normalized_keyword": identity[1],
                "family": candidate.family,
                "candidate_kind": candidate.candidate_kind,
                "rationale": candidate.rationale,
                "corpus_status": corpus_status,
                **analysis,
            }
        )
    candidate_results.sort(
        key=lambda row: (
            str(row["classification_id"]),
            str(row["normalized_keyword"]),
        )
    )

    language_counts = Counter(title_language(job.title) for job in jobs)
    posted_dates = sorted(
        date for job in jobs if (date := job.posted_date) is not None
    )
    posted_day_counts = Counter(date[:10] for date in posted_dates)

    jobs_by_classification: dict[str, set[str]] = defaultdict(set)
    classification_labels: dict[str, str] = {}
    for job in jobs:
        for path in job.paths:
            for node in path:
                classification_id = str(node["classification_id"])
                jobs_by_classification[classification_id].add(job.source_job_id)
                classification_labels[classification_id] = str(node["label"])
    classification_distribution = []
    for classification_id in sorted(jobs_by_classification):
        ids = jobs_by_classification[classification_id]
        classification_distribution.append(
            {
                "classification_id": classification_id,
                "label": classification_labels[classification_id],
                "job_count": len(ids),
                "title_covered_count": len(ids & current_title_covered),
                "title_coverage_rate": round(
                    len(ids & current_title_covered) / len(ids), 6
                ),
            }
        )

    pack_counts: dict[str, dict[str, Any]] = {}
    for row in keyword_entries:
        classification_id = str(row["classification_id"])
        pack = pack_counts.setdefault(
            classification_id,
            {
                "classification_id": classification_id,
                "classification_label": str(row["classification_label"]),
                "total_terms": 0,
                "enabled_terms": 0,
                "terms_with_execution_evidence": 0,
            },
        )
        pack["total_terms"] += 1
        pack["enabled_terms"] += int(bool(row["enabled"]))
        pack["terms_with_execution_evidence"] += int(
            row.get("last_run_at") is not None
        )

    corpus_size = len(jobs)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "offertoday_keyword_corpus_snapshot",
        "extracted_at": (extracted_at or utc_now()).isoformat(),
        "source_site": SOURCE_SITE,
        "settings": {
            "min_support": min_support,
            "example_limit": example_limit,
            "matching": "unicode_nfkc_casefold_latin_boundaries_cjk_contiguous_v1",
        },
        "population": {
            "published_jobs": corpus_size,
            "title_nonblank": sum(bool(job.title.strip()) for job in jobs),
            "description_nonblank": sum(bool(job.description.strip()) for job in jobs),
            "company_nonblank": sum(bool(job.company_name.strip()) for job in jobs),
            "posted_date_min": posted_dates[0] if posted_dates else None,
            "posted_date_max": posted_dates[-1] if posted_dates else None,
            "posted_day_counts": dict(sorted(posted_day_counts.items())),
            "title_language_counts": dict(sorted(language_counts.items())),
            "source_classification_path_count": sum(len(job.paths) for job in jobs),
            "source_classification_node_count": sum(
                len(path) for job in jobs for path in job.paths
            ),
            "explicit_primary_path_count": sum(
                int(bool(path and path[0].get("is_primary")))
                for job in jobs
                for path in job.paths
            ),
        },
        "staging": dict(staging_summary),
        "semantic_coverage": {
            "title_covered_jobs": len(current_title_covered),
            "title_coverage_rate": round(
                len(current_title_covered) / corpus_size, 6
            )
            if corpus_size
            else 0.0,
            "detail_covered_jobs": len(current_detail_covered),
            "detail_coverage_rate": round(
                len(current_detail_covered) / corpus_size, 6
            )
            if corpus_size
            else 0.0,
        },
        "classifications": [dict(row) for row in classifications],
        "classification_distribution": classification_distribution,
        "packs": [pack_counts[key] for key in sorted(pack_counts)],
        "keywords": keyword_results,
        "candidates": candidate_results,
        "limitations": [
            "The retained rows do not identify the triggering keyword or Query Target.",
            "Corpus matches are discovery evidence, not query recall or precision.",
            "Posted dates are heavily concentrated and are not a balanced time sample.",
            "No current keyword has populated execution-contribution evidence.",
        ],
    }


def extract_corpus_snapshot(
    *,
    candidate_file: Path,
    min_support: int,
    example_limit: int,
    statement_timeout_ms: int,
    session_factory: Callable[[], Any] = SessionLocal,
) -> dict[str, Any]:
    candidates = load_candidate_terms(candidate_file)
    with read_only_session(
        session_factory,
        statement_timeout_ms=statement_timeout_ms,
    ) as db:
        jobs = _load_jobs(db)
        classifications = _load_classifications(db)
        keyword_entries = _load_keyword_entries(db)
        staging_summary = _load_staging_summary(db)
    return build_corpus_snapshot(
        jobs=jobs,
        classifications=classifications,
        keyword_entries=keyword_entries,
        candidates=candidates,
        staging_summary=staging_summary,
        min_support=min_support,
        example_limit=example_limit,
    )


def build_probe_plan(
    corpus: Mapping[str, Any],
    *,
    max_additions: int,
    max_retirements: int,
    first_pass_pages: int,
    second_pass_pages: int,
    request_cap: int,
) -> dict[str, Any]:
    if min(
        max_additions,
        max_retirements,
        first_pass_pages,
        second_pass_pages,
        request_cap,
    ) < 1:
        raise ValueError("probe limits must be positive")
    classifications = [
        row
        for row in corpus.get("classifications", [])
        if isinstance(row, Mapping)
    ]
    root = next(
        (
            row
            for row in classifications
            if row.get("classification_id") == OFFERTODAY_IT_CLASSIFICATION_ID
            and row.get("is_active")
            and row.get("is_top_level")
        ),
        None,
    )
    if root is None:
        raise ValueError("Active OfferToday Information Technology root is missing")

    native_rows = [root] + sorted(
        (
            row
            for row in classifications
            if row.get("is_active")
            and row.get("parent_classification_id")
            == OFFERTODAY_IT_CLASSIFICATION_ID
        ),
        key=lambda row: str(row.get("classification_id") or ""),
    )
    native_targets = [
        ProbeTarget(
            key=f"native:{row['classification_id']}",
            kind="native_top_level" if row.get("is_top_level") else "native_child",
            classification_id=str(row["classification_id"]),
            category_id=int(str(row["native_id"])),
            keyword="",
            pages=1,
        )
        for row in native_rows
    ]

    current_rows = sorted(
        (
            row
            for row in corpus.get("keywords", [])
            if isinstance(row, Mapping)
            and row.get("enabled")
            and row.get("classification_id") == OFFERTODAY_IT_CLASSIFICATION_ID
        ),
        key=lambda row: str(row.get("normalized_keyword") or ""),
    )
    current_targets = [
        ProbeTarget(
            key=f"current:{row['normalized_keyword']}",
            kind="current_keyword",
            classification_id=OFFERTODAY_IT_CLASSIFICATION_ID,
            category_id=int(str(root["native_id"])),
            keyword=str(row["keyword"]),
            pages=1,
            corpus_detail_matches=int(row.get("detail_match_count") or 0),
        )
        for row in current_rows
    ]

    all_candidate_rows = sorted(
        (
            row
            for row in corpus.get("candidates", [])
            if isinstance(row, Mapping)
            and row.get("corpus_status")
            in {"probe_addition_candidate", "variant_or_replacement"}
        ),
        key=lambda row: (
            -int(row.get("uncovered_title_match_count") or 0),
            -int(row.get("title_match_count") or 0),
            -int(row.get("detail_match_count") or 0),
            str(row.get("normalized_keyword") or ""),
        ),
    )
    reserved_second_pass = 1 + min(max_retirements, len(current_targets)) * second_pass_pages
    fixed_request_max = len(native_targets) + len(current_targets) + reserved_second_pass
    per_addition_request_max = first_pass_pages + 1
    effective_addition_limit = min(
        max_additions,
        max(0, (request_cap - fixed_request_max) // per_addition_request_max),
    )
    if all_candidate_rows and effective_addition_limit < 1:
        raise ValueError(
            "Probe plan cannot fit any supported addition candidate inside "
            f"request cap {request_cap}"
        )
    candidate_rows = all_candidate_rows[:effective_addition_limit]
    addition_targets = [
        ProbeTarget(
            key=f"addition:{row['normalized_keyword']}",
            kind="addition_candidate",
            classification_id=OFFERTODAY_IT_CLASSIFICATION_ID,
            category_id=int(str(root["native_id"])),
            keyword=str(row["keyword"]),
            pages=first_pass_pages,
            corpus_detail_matches=int(row.get("detail_match_count") or 0),
        )
        for row in candidate_rows
    ]

    first_pass_request_max = (
        len(native_targets)
        + len(current_targets)
        + len(addition_targets) * first_pass_pages
    )
    addition_confirmation_request_max = len(addition_targets)
    if (
        first_pass_request_max
        + addition_confirmation_request_max
        + reserved_second_pass
        > request_cap
    ):
        raise ValueError(
            "Probe plan cannot fit native/current/addition and retirement verification "
            f"inside request cap {request_cap}"
        )
    return {
        "root": dict(root),
        "native_targets": native_targets,
        "current_targets": current_targets,
        "addition_targets": addition_targets,
        "max_retirements": max_retirements,
        "second_pass_pages": second_pass_pages,
        "first_pass_request_max": first_pass_request_max,
        "addition_confirmation_request_max": addition_confirmation_request_max,
        "reserved_second_pass": reserved_second_pass,
        "request_cap": request_cap,
    }


def _condition(target: ProbeTarget, *, pass_id: str) -> OfferTodayListingCondition:
    return OfferTodayListingCondition(
        search_family=f"keyword_review:{pass_id}:{target.kind}:{target.key}",
        category_id=target.category_id,
        keyword=target.keyword,
        endpoint="search",
        rcd_type=None,
    )


def _safe_stop_payload(result) -> dict[str, Any]:
    classifications = sorted(
        {
            str(observation.classification)
            for observation in result.observations
            if str(observation.classification) != "success"
        }
    )
    return {
        "stop_reason": str(result.stop_reason),
        "classifications": classifications,
        "gap_count": len(result.gaps),
        "identity_issue_count": len(result.identity_issues),
        "identity_conflict_count": len(result.identity_conflicts),
    }


async def _run_probe_group(
    *,
    targets: Sequence[ProbeTarget],
    pass_id: str,
    runtime: OfferTodayBrowserRuntime,
    budget: ProbeRequestBudget,
    page_delay_seconds: float,
) -> dict[str, Any]:
    if not targets:
        return {
            "pass_id": pass_id,
            "status": "complete",
            "targets": [],
            "stop": None,
        }
    pages = {target.pages for target in targets}
    if len(pages) != 1:
        raise ValueError("one probe group must use one page limit")
    page_limit = next(iter(pages))
    conditions = tuple(_condition(target, pass_id=pass_id) for target in targets)
    target_by_condition = {
        condition.condition_id: target
        for target, condition in zip(targets, conditions, strict=True)
    }
    sink = MemoryObservationSink()
    staging_sink = ResearchNoopListingStagingSink()
    runner = OfferTodayListingRunner(
        BudgetedListingTransport(runtime, budget),
        clock=time.perf_counter,
    )
    result = await runner.run(
        conditions=conditions,
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=page_limit,
            run_page_cap=max(1, budget.cap - budget.started),
            unique_job_cap=None,
            require_empty_confirmation=True,
            page_cap_behavior="retain-and-continue",
            stall_no_growth_page_count=None,
            max_stall_restarts_per_condition=0,
        ),
        retry_policy=ListingRetryPolicy(
            max_attempts_per_page=1,
            retry_delays_seconds=(),
            page_delay_seconds=page_delay_seconds,
        ),
        observation_sink=sink,
        staging_sink=staging_sink,
        session_mode="keyword-review-headless",
        request_policy=production_offertoday_listing_request_policy(page_size=10),
        terminal_policy=RESULT_TERMINAL_POLICY_ID,
    )

    observations_by_condition: dict[str, list[ListingPageObservation]] = defaultdict(list)
    for observation in result.observations:
        observations_by_condition[observation.condition_id].append(observation)
    outcomes_by_condition = {
        outcome.condition.condition_id: outcome for outcome in result.condition_outcomes
    }
    target_payloads: list[dict[str, Any]] = []
    for condition in conditions:
        target = target_by_condition[condition.condition_id]
        observations = observations_by_condition.get(condition.condition_id, [])
        job_ids = sorted(
            {
                identity.job_id
                for observation in observations
                if observation.classification == "success"
                for identity in observation.id_pairs
            }
        )
        outcome = outcomes_by_condition.get(condition.condition_id)
        observed_rows = sum(
            observation.row_count
            for observation in observations
            if observation.classification == "success"
        )
        result_examples_by_job_id: dict[str, dict[str, Any]] = {}
        for observation in observations:
            if observation.classification != "success":
                continue
            for row in observation.rows:
                if not row.job_id or not row.title or row.job_id in result_examples_by_job_id:
                    continue
                result_examples_by_job_id[row.job_id] = {
                    "job_id": row.job_id,
                    "title": row.title,
                    "title_language": row.title_language,
                    "job_function_codes": list(row.job_function_codes),
                }
        target_payloads.append(
            {
                "key": target.key,
                "kind": target.kind,
                "classification_id": target.classification_id,
                "category_id": target.category_id,
                "keyword": target.keyword,
                "corpus_detail_matches": target.corpus_detail_matches,
                "pages_observed": int(outcome.pages_observed) if outcome else 0,
                "observed_rows": observed_rows,
                "distinct_job_id_count": len(job_ids),
                "job_ids": job_ids[:MAX_EVIDENCE_IDS_PER_TARGET],
                "job_ids_truncated": len(job_ids) > MAX_EVIDENCE_IDS_PER_TARGET,
                "result_examples": [
                    result_examples_by_job_id[job_id]
                    for job_id in sorted(result_examples_by_job_id)[:10]
                ],
                "duplicate_rate": round(
                    0.0 if observed_rows == 0 else 1.0 - len(job_ids) / observed_rows,
                    6,
                ),
                "stop_reason": outcome.stop_reason if outcome else "not_started",
                "classifications": sorted(
                    {
                        str(observation.classification)
                        for observation in observations
                    }
                ),
            }
        )

    status = "complete" if result.is_complete or result.is_partial_success else "stopped"
    return {
        "pass_id": pass_id,
        "status": status,
        "targets": target_payloads,
        "stop": None if status == "complete" else _safe_stop_payload(result),
    }


def _target_id_map(passes: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for probe_pass in passes:
        for row in probe_pass.get("targets", []):
            if isinstance(row, Mapping):
                result[str(row.get("key") or "")] = {
                    str(value) for value in row.get("job_ids", [])
                }
    return result


def analyze_first_pass(
    passes: Sequence[Mapping[str, Any]],
    current_targets: Sequence[ProbeTarget],
    *,
    max_retirements: int,
) -> dict[str, Any]:
    ids = _target_id_map(passes)
    native_union = set().union(
        *(value for key, value in ids.items() if key.startswith("native:"))
    )
    current_by_key = {
        target.key: ids.get(target.key, set()) for target in current_targets
    }
    current_union = set().union(*current_by_key.values()) if current_by_key else set()
    contribution: dict[str, dict[str, int]] = {}
    for target in current_targets:
        own = current_by_key[target.key]
        other_union = set().union(
            *(value for key, value in current_by_key.items() if key != target.key)
        )
        contribution[target.key] = {
            "new_vs_native": len(own - native_union),
            "leave_one_out_new": len(own - native_union - other_union),
        }

    additions: dict[str, dict[str, int]] = {}
    for key, value in ids.items():
        if key.startswith("addition:"):
            additions[key] = {
                "new_vs_native": len(value - native_union),
                "new_vs_current_pack": len(value - native_union - current_union),
            }

    retirement = sorted(
        (
            target
            for target in current_targets
            if contribution[target.key]["leave_one_out_new"] == 0
        ),
        key=lambda target: (
            target.corpus_detail_matches,
            target.keyword.casefold(),
        ),
    )[:max_retirements]
    return {
        "native_job_ids": sorted(native_union),
        "current_pack_job_ids": sorted(current_union),
        "current_job_ids": {
            key: sorted(value) for key, value in sorted(current_by_key.items())
        },
        "current_contribution": contribution,
        "addition_contribution": additions,
        "retirement_targets": retirement,
    }


def finalize_probe_analysis(
    *,
    corpus: Mapping[str, Any],
    passes: Sequence[Mapping[str, Any]],
    first_analysis: Mapping[str, Any],
    retirement_targets: Sequence[ProbeTarget],
) -> dict[str, Any]:
    ids = _target_id_map(passes)
    second_native = ids.get(f"native-repeat:{OFFERTODAY_IT_CLASSIFICATION_ID}", set())
    current_ids_by_key = {
        str(key): {str(value) for value in values}
        for key, values in first_analysis.get("current_job_ids", {}).items()
    }
    current_results = dict(first_analysis.get("current_contribution", {}))
    retirement_results: dict[str, dict[str, Any]] = {}
    for target in retirement_targets:
        second_key = f"retirement-repeat:{normalize_offertoday_keyword(target.keyword)}"
        second_ids = ids.get(second_key, set())
        other_current = set().union(
            *(
                value
                for key, value in current_ids_by_key.items()
                if key != target.key
            )
        )
        second_incremental = second_ids - second_native - other_current
        first_incremental = int(
            current_results.get(target.key, {}).get("leave_one_out_new", 0)
        )
        retirement_results[target.key] = {
            "first_pass_leave_one_out_new": first_incremental,
            "second_pass_distinct_job_ids": len(second_ids),
            "second_pass_incremental_job_ids": len(second_incremental),
            "corpus_detail_matches": target.corpus_detail_matches,
            "decision": (
                "retire_candidate"
                if first_incremental == 0
                and len(second_incremental) == 0
                and target.corpus_detail_matches == 0
                else (
                    "needs_execution_evidence"
                    if first_incremental == 0 and len(second_incremental) == 0
                    else "retain"
                )
            ),
        }

    addition_results: dict[str, dict[str, Any]] = {}
    candidates_by_key = {
        f"addition:{row['normalized_keyword']}": row
        for row in corpus.get("candidates", [])
        if isinstance(row, Mapping)
    }
    for key, counts in first_analysis.get("addition_contribution", {}).items():
        corpus_row = candidates_by_key.get(key, {})
        new_count = int(counts.get("new_vs_current_pack", 0))
        addition_results[key] = {
            **dict(counts),
            "keyword": corpus_row.get("keyword"),
            "family": corpus_row.get("family"),
            "candidate_kind": corpus_row.get("candidate_kind"),
            "corpus_title_matches": corpus_row.get("title_match_count", 0),
            "corpus_detail_matches": corpus_row.get("detail_match_count", 0),
            "decision": "add" if new_count > 0 else "no_change",
        }

    stopped = any(probe_pass.get("status") != "complete" for probe_pass in passes)
    if stopped:
        verdict = "inconclusive"
    elif any(row["decision"] == "add" for row in addition_results.values()):
        verdict = "insufficient"
    else:
        verdict = "sufficient"
    return {
        "verdict": verdict,
        "addition_results": addition_results,
        "retirement_results": retirement_results,
        "native_distinct_job_ids": len(first_analysis.get("native_job_ids", [])),
        "current_pack_distinct_job_ids": len(
            first_analysis.get("current_pack_job_ids", [])
        ),
        "limitations": [
            "The probe is bounded comparative sampling, not natural exhaustion.",
            "OfferToday ranking and source state may differ between sessions.",
            "A zero bounded contribution is not an absolute zero-source result.",
        ],
    }


async def execute_live_probe(
    corpus: Mapping[str, Any],
    *,
    output_path: Path,
    max_additions: int,
    max_retirements: int,
    first_pass_pages: int,
    second_pass_pages: int,
    request_cap: int,
    page_delay_seconds: float,
    headed: bool,
    runtime_factory=OfferTodayBrowserRuntime,
) -> dict[str, Any]:
    plan = build_probe_plan(
        corpus,
        max_additions=max_additions,
        max_retirements=max_retirements,
        first_pass_pages=first_pass_pages,
        second_pass_pages=second_pass_pages,
        request_cap=request_cap,
    )
    budget = ProbeRequestBudget(request_cap)
    passes: list[dict[str, Any]] = []
    started_at = utc_now()
    status = "complete"
    safe_error: dict[str, str] | None = None
    try:
        async with runtime_factory(headed=headed) as runtime:
            passes.append(
                await _run_probe_group(
                    targets=plan["native_targets"],
                    pass_id="native-baseline",
                    runtime=runtime,
                    budget=budget,
                    page_delay_seconds=page_delay_seconds,
                )
            )
            if passes[-1]["status"] == "complete":
                passes.append(
                    await _run_probe_group(
                        targets=plan["current_targets"],
                        pass_id="current-pack",
                        runtime=runtime,
                        budget=budget,
                        page_delay_seconds=page_delay_seconds,
                    )
                )
            if passes[-1]["status"] == "complete":
                passes.append(
                    await _run_probe_group(
                        targets=plan["addition_targets"],
                        pass_id="addition-candidates",
                        runtime=runtime,
                        budget=budget,
                        page_delay_seconds=page_delay_seconds,
                    )
                )

        if all(probe_pass["status"] == "complete" for probe_pass in passes) and plan["addition_targets"]:
            confirmation_targets = [
                replace(target, pages=1) for target in plan["addition_targets"]
            ]
            async with runtime_factory(headed=headed) as runtime:
                passes.append(
                    await _run_probe_group(
                        targets=confirmation_targets,
                        pass_id="addition-confirmation",
                        runtime=runtime,
                        budget=budget,
                        page_delay_seconds=page_delay_seconds,
                    )
                )

        first_analysis = analyze_first_pass(
            passes,
            plan["current_targets"],
            max_retirements=max_retirements,
        )
        retirement_targets = first_analysis["retirement_targets"]
        if all(probe_pass["status"] == "complete" for probe_pass in passes) and retirement_targets:
            root = plan["root"]
            repeat_targets = [
                ProbeTarget(
                    key=f"native-repeat:{OFFERTODAY_IT_CLASSIFICATION_ID}",
                    kind="native_repeat",
                    classification_id=OFFERTODAY_IT_CLASSIFICATION_ID,
                    category_id=int(str(root["native_id"])),
                    keyword="",
                    pages=second_pass_pages,
                ),
                *[
                    ProbeTarget(
                        key=(
                            "retirement-repeat:"
                            f"{normalize_offertoday_keyword(target.keyword)}"
                        ),
                        kind="retirement_repeat",
                        classification_id=target.classification_id,
                        category_id=target.category_id,
                        keyword=target.keyword,
                        pages=second_pass_pages,
                        corpus_detail_matches=target.corpus_detail_matches,
                    )
                    for target in retirement_targets
                ],
            ]
            async with runtime_factory(headed=headed) as runtime:
                passes.append(
                    await _run_probe_group(
                        targets=repeat_targets,
                        pass_id="retirement-repeat",
                        runtime=runtime,
                        budget=budget,
                        page_delay_seconds=page_delay_seconds,
                    )
                )
        analysis = finalize_probe_analysis(
            corpus=corpus,
            passes=passes,
            first_analysis=first_analysis,
            retirement_targets=retirement_targets,
        )
        if any(probe_pass["status"] != "complete" for probe_pass in passes):
            status = "stopped"
    except Exception as exc:
        status = "stopped"
        first_analysis = {
            "native_job_ids": [],
            "current_pack_job_ids": [],
            "current_job_ids": {},
            "current_contribution": {},
            "addition_contribution": {},
            "retirement_targets": [],
        }
        analysis = {
            "verdict": "inconclusive",
            "addition_results": {},
            "retirement_results": {},
            "native_distinct_job_ids": 0,
            "current_pack_distinct_job_ids": 0,
            "limitations": ["Probe stopped before comparative evidence completed."],
        }
        safe_error = {
            "error_type": type(exc).__name__,
            "classification": str(getattr(exc, "classification", "unexpected")),
        }

    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "offertoday_keyword_live_probe",
        "started_at": started_at.isoformat(),
        "finished_at": utc_now().isoformat(),
        "status": status,
        "request_cap": request_cap,
        "requests_started": budget.started,
        "page_delay_seconds": page_delay_seconds,
        "settings": {
            "max_additions": max_additions,
            "max_retirements": max_retirements,
            "first_pass_pages": first_pass_pages,
            "second_pass_pages": second_pass_pages,
        },
        "passes": passes,
        "analysis": analysis,
        "error": safe_error,
    }
    write_json(output_path, payload)
    return payload


def _markdown_escape(value: Any) -> str:
    return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")


def _percentage(value: Any) -> str:
    return f"{float(value or 0) * 100:.1f}%"


def _addition_noise_risk(candidate_kind: Any) -> str:
    return {
        "acronym": (
            "Medium — boundary matching limits substring noise, but acronym "
            "meaning and role context can vary."
        ),
        "product": (
            "Medium — an exact product name can describe a tool dependency "
            "rather than the hiring role."
        ),
        "role_phrase": (
            "Low — the phrase is IT-specific, though it may duplicate broader "
            "support queries."
        ),
        "language_variant": (
            "Low–medium — the title phrase is IT-specific in this corpus, but "
            "it overlaps English or other Chinese variants."
        ),
    }.get(
        str(candidate_kind),
        "Medium — source ranking and cross-classification precision remain bounded-probe unknowns.",
    )


def build_review_payload(
    corpus: Mapping[str, Any],
    probe: Mapping[str, Any] | None,
) -> dict[str, Any]:
    analysis = dict((probe or {}).get("analysis") or {})
    verdict = str(analysis.get("verdict") or "inconclusive")
    if probe is None:
        verdict = "inconclusive"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "offertoday_keyword_review",
        "verdict": verdict,
        "corpus": dict(corpus),
        "probe": dict(probe) if probe is not None else None,
        "recommendations": {
            "add": sorted(
                (
                    {"key": key, **dict(row)}
                    for key, row in analysis.get("addition_results", {}).items()
                    if row.get("decision") == "add"
                ),
                key=lambda row: str(row.get("keyword") or row["key"]),
            ),
            "retire": sorted(
                (
                    {"key": key, **dict(row)}
                    for key, row in analysis.get("retirement_results", {}).items()
                    if row.get("decision") == "retire_candidate"
                ),
                key=lambda row: row["key"],
            ),
        },
    }


def render_markdown_review(review: Mapping[str, Any]) -> str:
    corpus = review["corpus"]
    probe = review.get("probe") or {}
    analysis = probe.get("analysis") or {}
    population = corpus["population"]
    semantic = corpus["semantic_coverage"]
    verdict = str(review["verdict"])
    verdict_text = {
        "sufficient": "SUFFICIENT — keep the current pack unchanged.",
        "insufficient": "INSUFFICIENT — review the evidence-backed add/retire proposal.",
        "inconclusive": "INCONCLUSIVE — no pack mutation is justified.",
    }.get(verdict, verdict.upper())
    lines = [
        "# OfferToday Keyword Pack coverage review",
        "",
        f"**Verdict: {verdict_text}**",
        "",
        "This review is read-only. It does not modify the database or Keyword Pack.",
        "",
        "## Snapshot",
        "",
        f"- Extracted at: `{corpus['extracted_at']}`",
        f"- Published OfferToday Jobs: {population['published_jobs']:,}",
        f"- Posted date range: {population['posted_date_min']} to {population['posted_date_max']}",
        f"- Source Classification Paths: {population['source_classification_path_count']:,}",
        f"- Explicit Primary paths: {population['explicit_primary_path_count']:,}",
        f"- Current title semantic coverage: {_percentage(semantic['title_coverage_rate'])}",
        f"- Current title+description semantic coverage: {_percentage(semantic['detail_coverage_rate'])}",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in corpus.get("limitations", []))
    lines.extend(f"- {item}" for item in analysis.get("limitations", []))
    lines.extend(
        [
            "",
            "## Corpus distribution",
            "",
            "### Title language",
            "",
            "| Language | Jobs |",
            "| --- | ---: |",
        ]
    )
    for language, count in population["title_language_counts"].items():
        lines.append(f"| {_markdown_escape(language)} | {int(count):,} |")
    lines.extend(
        [
            "",
            "### Source classifications",
            "",
            "| Classification | Label | Jobs | Title covered | Coverage |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for row in corpus.get("classification_distribution", []):
        lines.append(
            "| {classification_id} | {label} | {job_count:,} | "
            "{title_covered_count:,} | {coverage} |".format(
                classification_id=_markdown_escape(row["classification_id"]),
                label=_markdown_escape(row["label"]),
                job_count=int(row["job_count"]),
                title_covered_count=int(row["title_covered_count"]),
                coverage=_percentage(row["title_coverage_rate"]),
            )
        )

    lines.extend(
        [
            "",
            "## Pack accounting",
            "",
            "| Classification | Total | Enabled | Terms with run evidence |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in corpus.get("packs", []):
        lines.append(
            f"| {_markdown_escape(row['classification_id'])} | "
            f"{int(row['total_terms']):,} | {int(row['enabled_terms']):,} | "
            f"{int(row['terms_with_execution_evidence']):,} |"
        )

    lines.extend(
        [
            "",
            "## Candidate corpus evidence",
            "",
            "| Candidate | Kind | Title matches | Detail matches | Uncovered titles | Corpus status |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in corpus.get("candidates", []):
        lines.append(
            f"| {_markdown_escape(row['keyword'])} | {_markdown_escape(row['candidate_kind'])} | "
            f"{int(row['title_match_count']):,} | {int(row['detail_match_count']):,} | "
            f"{int(row['uncovered_title_match_count']):,} | "
            f"{_markdown_escape(row['corpus_status'])} |"
        )

    candidate_by_keyword = {
        str(row.get("keyword")): row
        for row in corpus.get("candidates", [])
        if isinstance(row, Mapping)
    }
    addition_rows = sorted(
        (
            row
            for row in analysis.get("addition_results", {}).values()
            if row.get("decision") == "add"
        ),
        key=lambda item: str(item.get("keyword") or ""),
    )
    if addition_rows:
        lines.extend(["", "### Representative persisted Job evidence", ""])
        for addition in addition_rows:
            keyword = str(addition.get("keyword") or "")
            lines.append(f"#### `{keyword}`")
            lines.append("")
            examples = candidate_by_keyword.get(keyword, {}).get("examples", [])
            for example in examples[:2]:
                lines.append(
                    "- `{source_job_id}` — {title} ({matched_field})".format(
                        source_job_id=_markdown_escape(example.get("source_job_id")),
                        title=_markdown_escape(example.get("title")),
                        matched_field=_markdown_escape(example.get("matched_field")),
                    )
                )
            lines.append("")

    if probe:
        lines.extend(
            [
                "",
                "## Bounded live probe",
                "",
                f"- Status: `{probe.get('status')}`",
                f"- Listing API requests: {int(probe.get('requests_started') or 0)} / {int(probe.get('request_cap') or 0)}",
                f"- Native sampled IDs: {int(analysis.get('native_distinct_job_ids') or 0):,}",
                f"- Current-pack sampled IDs: {int(analysis.get('current_pack_distinct_job_ids') or 0):,}",
                "",
                "### Addition contribution",
                "",
                "| Candidate | New vs native | New vs current pack | Decision |",
                "| --- | ---: | ---: | --- |",
            ]
        )
        for row in sorted(
            analysis.get("addition_results", {}).values(),
            key=lambda item: str(item.get("keyword") or ""),
        ):
            lines.append(
                f"| {_markdown_escape(row.get('keyword'))} | "
                f"{int(row.get('new_vs_native') or 0):,} | "
                f"{int(row.get('new_vs_current_pack') or 0):,} | "
                f"{_markdown_escape(row.get('decision'))} |"
            )
        lines.extend(
            [
                "",
                "### Retirement verification",
                "",
                "| Current term | Corpus matches | First unique | Second unique | Decision |",
                "| --- | ---: | ---: | ---: | --- |",
            ]
        )
        for key, row in sorted(analysis.get("retirement_results", {}).items()):
            lines.append(
                f"| {_markdown_escape(key.removeprefix('current:'))} | "
                f"{int(row.get('corpus_detail_matches') or 0):,} | "
                f"{int(row.get('first_pass_leave_one_out_new') or 0):,} | "
                f"{int(row.get('second_pass_incremental_job_ids') or 0):,} | "
                f"{_markdown_escape(row.get('decision'))} |"
            )

    lines.extend(
        [
            "",
            "## Recommendations",
            "",
        ]
    )
    additions = review["recommendations"]["add"]
    retirements = review["recommendations"]["retire"]
    if verdict == "sufficient":
        lines.append("No Keyword Pack change is recommended.")
    elif verdict == "insufficient":
        lines.append(
            f"Review {len(additions)} addition(s) and {len(retirements)} retirement candidate(s) before CSV preview/confirm."
        )
        if additions:
            lines.append(
                "- Add: "
                + ", ".join(f"`{row.get('keyword')}`" for row in additions)
            )
        if retirements:
            lines.append(
                "- Retire: "
                + ", ".join(
                    f"`{str(row['key']).removeprefix('current:')}`"
                    for row in retirements
                )
            )
        deferred = sorted(
            str(key).removeprefix("current:")
            for key, row in analysis.get("retirement_results", {}).items()
            if row.get("decision") == "needs_execution_evidence"
        )
        if deferred:
            lines.append(
                "- Keep pending more evidence: "
                + ", ".join(f"`{keyword}`" for keyword in deferred)
            )
        if additions or retirements:
            lines.extend(
                [
                    "",
                    "### Recall benefit and precision risk",
                    "",
                    "| Proposed change | Evidence-backed recall benefit | Precision/noise risk |",
                    "| --- | --- | --- |",
                ]
            )
        for row in additions:
            keyword = str(row.get("keyword") or "")
            candidate = candidate_by_keyword.get(keyword, {})
            lines.append(
                "| Add `{keyword}` | {new_ids:,} sampled ID(s) beyond the current "
                "pack; {titles:,} retained title and {details:,} detail matches. "
                "| {risk} |".format(
                    keyword=_markdown_escape(keyword),
                    new_ids=int(row.get("new_vs_current_pack") or 0),
                    titles=int(candidate.get("title_match_count") or 0),
                    details=int(candidate.get("detail_match_count") or 0),
                    risk=_markdown_escape(
                        _addition_noise_risk(candidate.get("candidate_kind"))
                    ),
                )
            )
        for row in retirements:
            keyword = str(row["key"]).removeprefix("current:")
            lines.append(
                "| Retire `{keyword}` | Removes one query after {corpus:,} corpus "
                "matches and zero unique IDs in both bounded passes. | Medium — "
                "missing historical query provenance and bounded sampling require "
                "a reversible CSV preview/confirm change. |".format(
                    keyword=_markdown_escape(keyword),
                    corpus=int(row.get("corpus_detail_matches") or 0),
                )
            )
    else:
        lines.append("No Keyword Pack change is justified until the probe completes safely.")

    lines.extend(
        [
            "",
            "## Current term corpus appendix",
            "",
            "| Keyword | Enabled | Title matches | Detail matches | Run evidence |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for row in corpus.get("keywords", []):
        lines.append(
            f"| {_markdown_escape(row['keyword'])} | "
            f"{'yes' if row['enabled'] else 'no'} | "
            f"{int(row['title_match_count']):,} | {int(row['detail_match_count']):,} | "
            f"{'yes' if row.get('last_run_at') else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Regeneration",
            "",
            "Use the commands recorded in this task's `implement.md`. Corpus extraction is PostgreSQL read-only; live probing has no database session.",
            "",
        ]
    )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    corpus = subparsers.add_parser("corpus", help="Extract a read-only corpus snapshot")
    corpus.add_argument("--candidate-file", type=Path, required=True)
    corpus.add_argument("--output", type=Path, required=True)
    corpus.add_argument("--min-support", type=int, default=DEFAULT_MIN_SUPPORT)
    corpus.add_argument("--example-limit", type=int, default=DEFAULT_EXAMPLE_LIMIT)
    corpus.add_argument(
        "--statement-timeout-ms",
        type=int,
        default=DEFAULT_STATEMENT_TIMEOUT_MS,
    )

    probe = subparsers.add_parser("probe", help="Run a bounded no-write live probe")
    probe.add_argument("--corpus", type=Path, required=True)
    probe.add_argument("--output", type=Path, required=True)
    probe.add_argument("--max-additions", type=int, default=DEFAULT_MAX_ADDITIONS)
    probe.add_argument("--max-retirements", type=int, default=DEFAULT_MAX_RETIREMENTS)
    probe.add_argument("--first-pass-pages", type=int, default=2)
    probe.add_argument("--second-pass-pages", type=int, default=1)
    probe.add_argument("--request-cap", type=int, default=DEFAULT_REQUEST_CAP)
    probe.add_argument(
        "--page-delay-seconds",
        type=float,
        default=DEFAULT_PAGE_DELAY_SECONDS,
    )
    probe.add_argument("--headed", action="store_true")

    report = subparsers.add_parser("report", help="Render corpus and probe evidence")
    report.add_argument("--corpus", type=Path, required=True)
    report.add_argument("--probe", type=Path)
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "corpus":
        snapshot = extract_corpus_snapshot(
            candidate_file=args.candidate_file,
            min_support=args.min_support,
            example_limit=args.example_limit,
            statement_timeout_ms=args.statement_timeout_ms,
        )
        write_json(args.output, snapshot)
        return 0
    if args.command == "probe":
        corpus = read_json(args.corpus)
        result = asyncio.run(
            execute_live_probe(
                corpus,
                output_path=args.output,
                max_additions=args.max_additions,
                max_retirements=args.max_retirements,
                first_pass_pages=args.first_pass_pages,
                second_pass_pages=args.second_pass_pages,
                request_cap=args.request_cap,
                page_delay_seconds=args.page_delay_seconds,
                headed=args.headed,
            )
        )
        return 0 if result["status"] == "complete" else 2
    corpus = read_json(args.corpus)
    probe = read_json(args.probe) if args.probe else None
    review = build_review_payload(corpus, probe)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        write_json(args.output, review)
    else:
        args.output.write_text(render_markdown_review(review) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
