import re
import csv
import html
import json
import uuid as uuid_lib
from datetime import date
from io import StringIO
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import and_, false, func, not_, or_
from typing import Literal, Optional, List
from pydantic import BaseModel, ConfigDict, Field
from app.database import get_db
from app.job_intelligence.source_attributes import SourceJobAttributes
from app.job_intelligence.skill_governance import (
    SkillGovernanceReadError,
    SkillGovernanceReader,
)
from app.api.job_search_parser import parse_search_expression, SearchExpressionError
from app.api.job_search_query import apply_parsed_clauses
from app.api.ai import _publish_run_request, _wait_for_terminal_run, _load_job_snapshot
from app.config import settings
from app.models import Job, Company
from app.models import JobSubcategory, JobCategory
from app.models.skill_governance import (
    GovernedJobSkill,
    GovernedJobSkillMention,
    GovernedSkill,
    GovernedSkillCategory,
    GovernedSkillTechnology,
    SkillTaxonomyActiveRevision,
)
from app.models.source_job_attributes import (
    EmploymentType,
    JobEmploymentType,
    JobSourceClassificationPath,
)
from app.schemas import (
    JobSchema,
    JobCreateSchema,
    ManualJobCreateSchema,
    JobDetailSchema,
    JobTaxonomySchema,
)
from app.schemas.job import EmploymentTypeSchema, SourceClassificationPathSchema
from app.services.enrichment_run_service import (
    ActiveEnrichmentRunError,
    EnrichmentRunService,
)
from app.services.ai_runtime_settings_service import (
    ensure_profile_runtime_ready,
    ProfileRuntimeNotReadyError,
)
from app.schemas.job_search import (
    JobSearchRequestSchema,
    JobSearchFiltersSchema,
    JobSearchLayerSchema,
    JobSearchScopeSchema,
    JobSearchLayerSummarySchema,
    SourceSiteFilter,
)
from app.services.retrieval_client import (
    RetrievalClient,
    RetrievalClientResponseError,
    RetrievalClientUnavailableError,
)
from app.services.retrieval_service import RetrievalService
from app.utils.location_normalizer import (
    DISTRICT_TO_REGION,
    REGION_ORDER,
    REGION_OTHER,
    SPECIAL_REGION_VALUES,
    normalize_location,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])
JOB_SEARCH_EXPORT_MAX_ROWS = 10000
JOBSDB_BASE_URL = "https://hk.jobsdb.com/job"
CTGOODJOBS_BASE_URL = "https://jobs.ctgoodjobs.hk/job"
SOURCE_SITE_LABELS = {
    "jobsdb": "JobsDB",
    "ctgoodjobs": "CTGoodJobs",
    "offertoday": "OfferToday",
}
JOB_SEARCH_EXPORT_FIELDNAMES = [
    "job_id",
    "original_job_url",
    "title",
    "company_name",
    "company_industry",
    "location",
    "employment_type",
    "posted_date",
    "expiry_date",
    "is_expired",
    "salary_range",
    "salary_min",
    "salary_max",
    "salary_currency",
    "source_classification_name",
    "source_subclassification_name",
    "job_taxonomy_path",
    "ai_summary",
    "experience_level",
    "experience_min_years",
    "experience_max_years",
    "experience_summary",
    "skills",
    "company_ai_description",
    "description_text",
]


def _source_attribute_load_options(*, include_labels: bool = False):
    options = [
        selectinload(Job.source_classification_paths).options(
            selectinload(JobSourceClassificationPath.nodes),
            joinedload(JobSourceClassificationPath.source_catalog_revision),
        ),
        selectinload(Job.employment_type_assignments).joinedload(
            JobEmploymentType.employment_type
        ),
    ]
    if include_labels:
        options.append(selectinload(Job.source_employment_labels))
    return tuple(options)


# Response schemas for search
class JobWithCompanySchema(BaseModel):
    """Job with company name for search results."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: str
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    salary_range: Optional[str] = None
    employment_type: Optional[str] = None
    subcategory_id: Optional[UUID] = None
    job_taxonomy: Optional[JobTaxonomySchema] = None
    company_name: Optional[str] = None
    posted_date: Optional[str] = None
    source_classification_paths: List[SourceClassificationPathSchema] = Field(
        default_factory=list
    )
    employment_types: List[EmploymentTypeSchema] = Field(default_factory=list)


class JobSearchResponse(BaseModel):
    """Paginated job search response."""

    jobs: List[JobWithCompanySchema]
    total: int
    page: int
    page_size: int
    total_pages: int
    applied_scope: Optional[JobSearchScopeSchema] = None
    layer_summaries: Optional[List[JobSearchLayerSummarySchema]] = None


def _validate_scope_expressions(request: JobSearchRequestSchema) -> None:
    for layer in request.scope.layers:
        try:
            parse_search_expression(layer.text_expression)
        except SearchExpressionError as exc:
            raise HTTPException(status_code=422, detail=exc.to_dict()) from exc


class LocationHierarchyItem(BaseModel):
    """Available districts within a normalized region."""

    region: str
    districts: List[str]


class EmploymentTypeOption(BaseModel):
    code: str
    label: str
    order: int


class SourceClassificationOption(BaseModel):
    id: str
    label: str
    source: str
    path: str


class FilterOptionsResponse(BaseModel):
    """Available filter options."""

    locations: List[str]
    regions: List[str]
    location_hierarchy: List[LocationHierarchyItem]
    employment_types: List[EmploymentTypeOption]
    source_classifications: List[SourceClassificationOption]
    industries: List[str]


def _build_location_hierarchy(raw_locations: List[str]) -> List[LocationHierarchyItem]:
    districts_by_region: dict[str, set[str]] = {
        region: set() for region in REGION_ORDER
    }

    for raw_location in raw_locations:
        normalized = normalize_location(raw_location)
        if normalized.region not in districts_by_region:
            districts_by_region[normalized.region] = set()
        if normalized.district:
            districts_by_region[normalized.region].add(normalized.district)

    return [
        LocationHierarchyItem(
            region=region,
            districts=sorted(districts_by_region.get(region, set())),
        )
        for region in REGION_ORDER
    ]


def _location_matches_district(column, district: str):
    return or_(
        column == district,
        column.ilike(f"%, {district}"),
    )


def _recognized_non_other_location(column):
    exact_values = [
        raw_value
        for raw_value, normalized_value in SPECIAL_REGION_VALUES.items()
        if normalized_value != REGION_OTHER
    ]
    clauses = []
    if exact_values:
        clauses.append(column.in_(exact_values))
    clauses.extend(
        _location_matches_district(column, district) for district in DISTRICT_TO_REGION
    )
    return or_(*clauses) if clauses else false()


def _location_matches_region(column, region: str):
    if region == REGION_OTHER:
        other_exact_values = [
            raw_value
            for raw_value, normalized_value in SPECIAL_REGION_VALUES.items()
            if normalized_value == REGION_OTHER
        ]
        return or_(
            column.is_(None),
            column == "",
            column.in_(other_exact_values),
            and_(
                column.is_not(None),
                column != "",
                not_(_recognized_non_other_location(column)),
                not_(column.in_(other_exact_values)),
            ),
        )

    exact_values = [
        raw_value
        for raw_value, normalized_value in SPECIAL_REGION_VALUES.items()
        if normalized_value == region
    ]
    clauses = []
    if exact_values:
        clauses.append(column.in_(exact_values))
    clauses.extend(
        _location_matches_district(column, district)
        for district, district_region in DISTRICT_TO_REGION.items()
        if district_region == region
    )
    return or_(*clauses) if clauses else false()


def parse_search_tokens(query: Optional[str]) -> list[str]:
    """Normalize a raw query string into non-empty comma/space separated tokens."""
    if not query:
        return []

    return [token for token in re.split(r"[\s,]+", query.strip()) if token]


def _validate_experience_query_window(
    experience_years_from: Optional[int],
    experience_years_to: Optional[int],
):
    if (
        experience_years_from is not None
        and experience_years_to is not None
        and experience_years_from > experience_years_to
    ):
        raise HTTPException(
            status_code=422,
            detail="experience_years_from must be less than or equal to experience_years_to",
        )


def _build_experience_query_window(
    experience_years_from: Optional[int],
    experience_years_to: Optional[int],
):
    # Inclusive query window: [from, to]. Any side may be unbounded (None).
    return (experience_years_from, experience_years_to)


def _build_job_experience_window(job_min_years_column, job_max_years_column):
    # Inclusive job window: [min, max]. Any side may be unbounded (NULL).
    return (job_min_years_column, job_max_years_column)


def _experience_windows_overlap_clause(query_window, job_window, job_level_column):
    """
    Build an overlap clause between a query window and a job window.

    Semantics (kept intentionally identical to prior inline implementation):
    - If any experience filter is active, treat `not_specified` + null bounds as a
      virtual `[0, 1]` interval.
    - Otherwise exclude jobs with both min/max unspecified.
    - For query lower bound: job.max is NULL OR job.max >= query.from
    - For query upper bound: job.min is NULL OR job.min <= query.to
    """
    query_from, query_to = query_window
    job_min_years, job_max_years = job_window
    has_explicit_bounds = or_(
        job_min_years.is_not(None),
        job_max_years.is_not(None),
    )
    unspecified_entry_level = and_(
        job_level_column == "not_specified",
        job_min_years.is_(None),
        job_max_years.is_(None),
    )

    clauses = [
        or_(
            has_explicit_bounds,
            unspecified_entry_level,
        )
    ]

    if query_from is not None:
        clauses.append(
            or_(
                and_(
                    has_explicit_bounds,
                    or_(
                        job_max_years.is_(None),
                        job_max_years >= query_from,
                    ),
                ),
                and_(
                    unspecified_entry_level,
                    query_from <= 1,
                ),
            )
        )
    if query_to is not None:
        clauses.append(
            or_(
                and_(
                    has_explicit_bounds,
                    or_(
                        job_min_years.is_(None),
                        job_min_years <= query_to,
                    ),
                ),
                unspecified_entry_level,
            )
        )

    return and_(*clauses)


def _coerce_uuid_list(values: Optional[List[str]]) -> List[UUID]:
    coerced: List[UUID] = []
    for raw_value in values or []:
        if raw_value is None:
            continue
        try:
            coerced.append(UUID(str(raw_value)))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid taxonomy identifier: {raw_value}",
            ) from exc
    return coerced


def _join_active_skill_projection(query):
    return (
        query.join(
            GovernedJobSkill,
            GovernedJobSkill.job_id == Job.id,
        )
        .join(
            SkillTaxonomyActiveRevision,
            and_(
                SkillTaxonomyActiveRevision.singleton_key == "skill-taxonomy",
                SkillTaxonomyActiveRevision.revision_id
                == GovernedJobSkill.taxonomy_revision_id,
            ),
        )
        .join(
            GovernedSkill,
            and_(
                GovernedSkill.id == GovernedJobSkill.skill_id,
                GovernedSkill.revision_id == GovernedJobSkill.taxonomy_revision_id,
            ),
        )
        .join(
            GovernedSkillTechnology,
            and_(
                GovernedSkillTechnology.id == GovernedSkill.technology_id,
                GovernedSkillTechnology.revision_id == GovernedSkill.revision_id,
            ),
        )
        .join(
            GovernedSkillCategory,
            and_(
                GovernedSkillCategory.id == GovernedSkillTechnology.category_id,
                GovernedSkillCategory.revision_id
                == GovernedSkillTechnology.revision_id,
            ),
        )
        .filter(
            GovernedSkill.is_active.is_(True),
            GovernedSkillTechnology.is_active.is_(True),
            GovernedSkillCategory.is_active.is_(True),
        )
    )


def _apply_structured_filters(query, filters: JobSearchFiltersSchema):
    _validate_experience_query_window(
        filters.experience_years_from,
        filters.experience_years_to,
    )

    if filters.source_site:
        query = query.filter(Job.source_site == filters.source_site)
    if filters.location and not filters.region and not filters.district:
        query = query.filter(Job.location.ilike(f"%{filters.location}%"))
    query = SourceJobAttributes(query.session).build_filters(
        query,
        source_classification_ids=filters.source_classification_ids or [],
        employment_type_codes=filters.employment_type_codes or [],
    )
    if filters.industry:
        query = query.filter(Company.industry == filters.industry)
    if filters.posted_date_from:
        query = query.filter(func.date(Job.posted_date) >= filters.posted_date_from)
    if filters.posted_date_to:
        query = query.filter(func.date(Job.posted_date) <= filters.posted_date_to)
    if (
        filters.experience_years_from is not None
        or filters.experience_years_to is not None
    ):
        query_window = _build_experience_query_window(
            experience_years_from=filters.experience_years_from,
            experience_years_to=filters.experience_years_to,
        )
        job_window = _build_job_experience_window(
            job_min_years_column=Job.experience_min_years,
            job_max_years_column=Job.experience_max_years,
        )
        query = query.filter(
            _experience_windows_overlap_clause(
                query_window,
                job_window,
                Job.experience_level,
            )
        )

    skill_ids = _coerce_uuid_list(filters.skill_ids)
    technology_ids = _coerce_uuid_list(filters.technology_ids)
    skill_category_ids = _coerce_uuid_list(filters.skill_category_ids)
    subcategory_ids = _coerce_uuid_list(filters.subcategory_ids)
    job_category_ids = _coerce_uuid_list(filters.job_category_ids)
    domain_ids = _coerce_uuid_list(filters.domain_ids)

    if skill_ids:
        query = (
            _join_active_skill_projection(query)
            .filter(GovernedSkill.id.in_(skill_ids))
            .distinct()
        )
    elif technology_ids:
        query = (
            _join_active_skill_projection(query)
            .filter(GovernedSkill.technology_id.in_(technology_ids))
            .distinct()
        )
    elif skill_category_ids:
        query = (
            _join_active_skill_projection(query)
            .filter(GovernedSkillTechnology.category_id.in_(skill_category_ids))
            .distinct()
        )
    elif filters.skills:
        query = (
            _join_active_skill_projection(query)
            .filter(GovernedSkill.name.in_(filters.skills))
            .distinct()
        )

    if subcategory_ids:
        query = query.filter(Job.subcategory_id.in_(subcategory_ids))
    elif job_category_ids:
        query = query.join(JobSubcategory).filter(
            JobSubcategory.category_id.in_(job_category_ids)
        )
    elif domain_ids:
        query = (
            query.join(JobSubcategory)
            .join(JobCategory)
            .filter(JobCategory.domain_id.in_(domain_ids))
        )

    if filters.district:
        query = query.filter(_location_matches_district(Job.location, filters.district))
    if filters.region:
        query = query.filter(_location_matches_region(Job.location, filters.region))
    if filters.salary_min is not None:
        query = query.filter(Job.salary_max >= filters.salary_min)
    if filters.salary_max is not None:
        query = query.filter(Job.salary_min <= filters.salary_max)

    return query


def _summarize_layer(layer: JobSearchLayerSchema) -> JobSearchLayerSummarySchema:
    parts = []
    for clause in parse_search_expression(layer.text_expression):
        if clause.clause_type == "broad":
            parts.append(f"Broad: {clause.value}")
        elif clause.clause_type == "exact":
            parts.append(f"Exact: ={clause.value}")
        elif clause.clause_type == "phrase":
            parts.append(f'Phrase: "{clause.value}"')

    filters = layer.structured_filters
    if filters.source_site:
        parts.append(
            f"Source: {SOURCE_SITE_LABELS.get(filters.source_site, filters.source_site)}"
        )
    if filters.industry:
        parts.append(f"Industry: {filters.industry}")
    if filters.employment_type_codes:
        parts.append("Employment Types: " + ", ".join(filters.employment_type_codes))

    return JobSearchLayerSummarySchema(
        client_id=layer.client_id,
        label=" | ".join(parts) if parts else "Structured filters only",
    )


def _build_query_from_scope(db: Session, scope: JobSearchScopeSchema):
    query = (
        db.query(Job, Company)
        .join(Company, Job.company_id == Company.id)
        .filter(Job.is_deleted.is_(False))
        .options(
            selectinload(Job.governed_job_skills).joinedload(GovernedJobSkill.skill),
            joinedload(Job.company),
            joinedload(Job.subcategory)
            .joinedload(JobSubcategory.category)
            .joinedload(JobCategory.domain),
            *_source_attribute_load_options(),
        )
    )

    for layer in scope.layers:
        query = apply_parsed_clauses(
            query, parse_search_expression(layer.text_expression)
        )
        query = _apply_structured_filters(query, layer.structured_filters)

    return query


def _build_legacy_scope(
    *,
    q: Optional[str],
    source_site: Optional[SourceSiteFilter | str],
    location: Optional[str],
    region: Optional[str],
    district: Optional[str],
    employment_type: Optional[str],
    source_classification_ids: Optional[List[str]],
    employment_type_codes: Optional[List[str]],
    industry: Optional[str],
    posted_date_from: Optional[date],
    posted_date_to: Optional[date],
    experience_years_from: Optional[int],
    experience_years_to: Optional[int],
    skills: Optional[List[str]],
    skill_ids: Optional[List[str]],
    technology_ids: Optional[List[str]],
    skill_category_ids: Optional[List[str]],
    subcategory_ids: Optional[List[str]],
    job_category_ids: Optional[List[str]],
    domain_ids: Optional[List[str]],
    salary_min: Optional[int],
    salary_max: Optional[int],
):
    return JobSearchScopeSchema(
        layers=[
            JobSearchLayerSchema(
                client_id="legacy-root",
                text_expression=q or "",
                structured_filters=JobSearchFiltersSchema(
                    source_site=source_site,
                    location=location,
                    region=region,
                    district=district,
                    employment_type=employment_type,
                    source_classification_ids=source_classification_ids,
                    employment_type_codes=employment_type_codes,
                    industry=industry,
                    posted_date_from=posted_date_from,
                    posted_date_to=posted_date_to,
                    experience_years_from=experience_years_from,
                    experience_years_to=experience_years_to,
                    skills=skills,
                    skill_ids=skill_ids,
                    technology_ids=technology_ids,
                    skill_category_ids=skill_category_ids,
                    subcategory_ids=subcategory_ids,
                    job_category_ids=job_category_ids,
                    domain_ids=domain_ids,
                    salary_min=salary_min,
                    salary_max=salary_max,
                ),
            )
        ]
    )


def _build_search_response(
    query,
    *,
    page: int,
    page_size: int,
    applied_scope: Optional[JobSearchScopeSchema] = None,
    layer_summaries: Optional[List[JobSearchLayerSummarySchema]] = None,
    preserve_query_order: bool = False,
):
    offset = (page - 1) * page_size
    total = query.order_by(None).count()
    results_query = query
    if not preserve_query_order:
        results_query = results_query.order_by(
            func.coalesce(Job.posted_date, Job.created_at).desc()
        )
    results = results_query.offset(offset).limit(page_size).all()
    return _build_search_response_from_results(
        results,
        total=total,
        page=page,
        page_size=page_size,
        applied_scope=applied_scope,
        layer_summaries=layer_summaries,
    )


def _build_search_response_from_results(
    results,
    *,
    total: int,
    page: int,
    page_size: int,
    applied_scope: Optional[JobSearchScopeSchema] = None,
    layer_summaries: Optional[List[JobSearchLayerSummarySchema]] = None,
):
    jobs = []
    for job, company in results:
        jobs.append(
            JobWithCompanySchema(
                id=job.id,
                job_id=job.job_id,
                title=job.title,
                description=job.description[:200] + "..."
                if job.description and len(job.description) > 200
                else job.description,
                location=job.location,
                salary_range=job.salary_range,
                employment_type=job.employment_type,
                subcategory_id=job.subcategory_id,
                job_taxonomy=job.job_taxonomy,
                company_name=company.name if company else None,
                posted_date=job.posted_date.isoformat() if job.posted_date else None,
                source_classification_paths=job.source_classification_paths,
                employment_types=job.employment_types,
            )
        )

    total_pages = (total + page_size - 1) // page_size
    return JobSearchResponse(
        jobs=jobs,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        applied_scope=applied_scope,
        layer_summaries=layer_summaries,
    )


def _raw_data_mapping(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _strip_source_prefix(job_id: str, source_site: str) -> str:
    prefix = f"{source_site}:"
    return job_id[len(prefix) :] if job_id.startswith(prefix) else job_id


def _build_original_job_url(job) -> str:
    original_job_url = getattr(job, "original_job_url", None)
    if isinstance(original_job_url, str):
        return original_job_url

    job_id = job.job_id or ""
    if not job_id:
        return ""

    source_site = (getattr(job, "source_site", None) or "jobsdb").strip().lower()
    raw_data = _raw_data_mapping(getattr(job, "raw_data", None))
    for key in ("canonical_job_url", "job_url", "url"):
        value = raw_data.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value

    if source_site == "ctgoodjobs":
        return f"{CTGOODJOBS_BASE_URL}/{_strip_source_prefix(job_id, source_site)}"
    return f"{JOBSDB_BASE_URL}/{job_id}"


def _strip_html_text(value: Optional[str]) -> str:
    if not value:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(without_tags).split())


def _build_export_rows(query):
    results = query.order_by(Job.posted_date.desc().nullslast()).all()
    return _build_export_rows_from_results(results)


def _build_export_rows_from_results(results):
    rows = []
    for job, company in results:
        rows.append(
            {
                "job_id": job.job_id,
                "original_job_url": _build_original_job_url(job),
                "title": job.title or "",
                "company_name": company.name if company else "",
                "company_industry": company.industry if company else "",
                "location": job.location or "",
                "employment_type": job.employment_type or "",
                "posted_date": job.posted_date.isoformat() if job.posted_date else "",
                "expiry_date": job.expiry_date or "",
                "is_expired": ""
                if job.is_expired is None
                else str(job.is_expired).lower(),
                "salary_range": job.salary_range or "",
                "salary_min": "" if job.salary_min is None else str(job.salary_min),
                "salary_max": "" if job.salary_max is None else str(job.salary_max),
                "salary_currency": job.salary_currency or "",
                "source_classification_name": job.source_classification_name or "",
                "source_subclassification_name": job.source_subclassification_name
                or "",
                "job_taxonomy_path": job.job_taxonomy_path or "",
                "ai_summary": job.ai_summary or "",
                "experience_level": job.experience_level or "",
                "experience_min_years": ""
                if job.experience_min_years is None
                else str(job.experience_min_years),
                "experience_max_years": ""
                if job.experience_max_years is None
                else str(job.experience_max_years),
                "experience_summary": job.experience_summary or "",
                "skills": " | ".join(job.skills),
                "company_ai_description": company.ai_description if company else "",
                "description_text": _strip_html_text(job.description),
            }
        )
    return rows


def _serialize_export_rows(rows) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=JOB_SEARCH_EXPORT_FIELDNAMES)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _build_csv_export_response(rows) -> Response:
    return Response(
        content=_serialize_export_rows(rows),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="job-search-export.csv"',
        },
    )


def _validate_export_row_limit(total: int) -> None:
    if total > JOB_SEARCH_EXPORT_MAX_ROWS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "job_search_export_too_large",
                "message": (
                    f"Export scope contains {total} rows, exceeding the limit of "
                    f"{JOB_SEARCH_EXPORT_MAX_ROWS}. Narrow the scope before exporting."
                ),
            },
        )


async def _search_via_retrieval_api(
    request: JobSearchRequestSchema,
    *,
    layer_summaries: List[JobSearchLayerSummarySchema],
) -> JobSearchResponse:
    payload = request.model_dump(mode="json")
    payload["layer_summaries"] = [
        layer_summary.model_dump(mode="json") for layer_summary in layer_summaries
    ]

    client = RetrievalClient(base_url=settings.retrieval_api_url)
    try:
        response_payload = await client.search_jobs(payload)
    except RetrievalClientResponseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except RetrievalClientUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "retrieval_api_unavailable",
                "message": str(exc),
            },
        ) from exc

    return JobSearchResponse.model_validate(response_payload)


async def _export_via_retrieval_api(request: JobSearchRequestSchema) -> Response:
    payload = request.model_dump(mode="json")

    client = RetrievalClient(base_url=settings.retrieval_api_url)
    try:
        csv_content = await client.export_jobs_csv(payload)
    except RetrievalClientResponseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except RetrievalClientUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "retrieval_api_unavailable",
                "message": str(exc),
            },
        ) from exc

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="job-search-export.csv"',
        },
    )


@router.get("", response_model=list[JobSchema])
async def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List all jobs with pagination."""
    jobs = (
        db.query(Job)
        .options(*_source_attribute_load_options())
        .filter(Job.is_deleted.is_(False))
        .offset(skip)
        .limit(limit)
        .all()
    )
    return jobs


@router.get("/search", response_model=JobSearchResponse)
async def search_jobs(
    q: Optional[str] = Query(None, description="Full-text search query"),
    source_site: Optional[Literal["jobsdb", "ctgoodjobs", "offertoday", ""]] = Query(
        None,
        description="Filter by job source site",
    ),
    location: Optional[str] = Query(None, description="Filter by location"),
    region: Optional[str] = Query(None, description="Filter by normalized region"),
    district: Optional[str] = Query(None, description="Filter by normalized district"),
    employment_type: Optional[str] = Query(
        None, description="Filter by employment type"
    ),
    source_classification_ids: Optional[List[str]] = Query(
        None,
        description="Filter by Source Classification identities",
    ),
    employment_type_codes: Optional[List[str]] = Query(
        None,
        description="Filter by governed Employment Type codes",
    ),
    industry: Optional[str] = Query(None, description="Filter by industry"),
    posted_date_from: Optional[date] = Query(
        None, description="Filter by posted date from"
    ),
    posted_date_to: Optional[date] = Query(
        None, description="Filter by posted date to"
    ),
    experience_years_from: Optional[int] = Query(
        None, ge=0, description="Filter by minimum required experience years"
    ),
    experience_years_to: Optional[int] = Query(
        None, ge=0, description="Filter by maximum required experience years"
    ),
    skills: Optional[List[str]] = Query(None, description="Filter by skills"),
    skill_ids: Optional[List[str]] = Query(
        None, description="Filter by skill IDs (L3)"
    ),
    technology_ids: Optional[List[str]] = Query(
        None, description="Filter by technology IDs (L2)"
    ),
    skill_category_ids: Optional[List[str]] = Query(
        None, description="Filter by skill category IDs (L1)"
    ),
    subcategory_ids: Optional[List[str]] = Query(
        None, description="Filter by job subcategory IDs (L3)"
    ),
    job_category_ids: Optional[List[str]] = Query(
        None, description="Filter by job category IDs (L2)"
    ),
    domain_ids: Optional[List[str]] = Query(
        None, description="Filter by job domain IDs (L1)"
    ),
    salary_min: Optional[int] = Query(None, ge=0, description="Minimum salary (HKD)"),
    salary_max: Optional[int] = Query(None, ge=0, description="Maximum salary (HKD)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
):
    """Search jobs with filters and pagination."""
    scope = _build_legacy_scope(
        q=q,
        source_site=source_site,
        location=location,
        region=region,
        district=district,
        employment_type=employment_type,
        source_classification_ids=source_classification_ids,
        employment_type_codes=employment_type_codes,
        industry=industry,
        posted_date_from=posted_date_from,
        posted_date_to=posted_date_to,
        experience_years_from=experience_years_from,
        experience_years_to=experience_years_to,
        skills=skills,
        skill_ids=skill_ids,
        technology_ids=technology_ids,
        skill_category_ids=skill_category_ids,
        subcategory_ids=subcategory_ids,
        job_category_ids=job_category_ids,
        domain_ids=domain_ids,
        salary_min=salary_min,
        salary_max=salary_max,
    )
    query = _build_query_from_scope(db, scope)
    return _build_search_response(query, page=page, page_size=page_size)


@router.post("/search", response_model=JobSearchResponse)
async def search_jobs_post(
    request: JobSearchRequestSchema,
    db: Session = Depends(get_db),
):
    _validate_scope_expressions(request)
    layer_summaries = [_summarize_layer(layer) for layer in request.scope.layers]

    if request.retrieval_mode != "lexical":
        return await _search_via_retrieval_api(
            request,
            layer_summaries=layer_summaries,
        )

    return RetrievalService(db).search(
        request,
        layer_summaries=layer_summaries,
    )


@router.post("/search/export")
async def export_jobs_search_scope(
    request: JobSearchRequestSchema,
    db: Session = Depends(get_db),
):
    _validate_scope_expressions(request)
    if request.retrieval_mode != "lexical":
        return await _export_via_retrieval_api(request)

    query = _build_query_from_scope(db, request.scope)
    total = query.order_by(None).count()
    _validate_export_row_limit(total)

    rows = _build_export_rows(query)
    return _build_csv_export_response(rows)


@router.get("/filters", response_model=FilterOptionsResponse)
async def get_filter_options(db: Session = Depends(get_db)):
    """Get available filter options from existing jobs."""
    # Get unique locations
    locations = (
        db.query(Job.location)
        .filter(Job.is_deleted.is_(False), Job.location.isnot(None), Job.location != "")
        .distinct()
        .all()
    )

    employment_types = (
        db.query(EmploymentType)
        .join(
            JobEmploymentType,
            JobEmploymentType.employment_type_code == EmploymentType.code,
        )
        .join(Job, Job.id == JobEmploymentType.job_id)
        .filter(Job.is_deleted.is_(False))
        .distinct()
        .order_by(EmploymentType.sort_order)
        .all()
    )

    classification_paths = (
        db.query(JobSourceClassificationPath)
        .options(joinedload(JobSourceClassificationPath.nodes))
        .join(Job, Job.id == JobSourceClassificationPath.job_id)
        .filter(Job.is_deleted.is_(False))
        .order_by(
            JobSourceClassificationPath.source_site,
            JobSourceClassificationPath.source_order,
        )
        .all()
    )
    source_classifications: list[SourceClassificationOption] = []
    seen_classification_ids: set[str] = set()
    for path in classification_paths:
        breadcrumb: list[str] = []
        for node in path.nodes:
            breadcrumb.append(node.label)
            if node.source_classification_id in seen_classification_ids:
                continue
            seen_classification_ids.add(node.source_classification_id)
            source_classifications.append(
                SourceClassificationOption(
                    id=node.source_classification_id,
                    label=node.label,
                    source=path.source_site,
                    path=" / ".join(breadcrumb),
                )
            )

    # Get unique industries from companies
    industries = (
        db.query(Company.industry)
        .filter(
            Company.is_deleted.is_(False),
            Company.industry.isnot(None),
            Company.industry != "",
        )
        .distinct()
        .all()
    )

    raw_locations = [loc[0] for loc in locations if loc[0]]

    return FilterOptionsResponse(
        locations=raw_locations,
        regions=REGION_ORDER,
        location_hierarchy=_build_location_hierarchy(raw_locations),
        employment_types=[
            EmploymentTypeOption(
                code=item.code,
                label=item.label,
                order=item.sort_order,
            )
            for item in employment_types
        ],
        source_classifications=source_classifications,
        industries=[ind[0] for ind in industries if ind[0]],
    )


@router.get("/{job_id}", response_model=JobDetailSchema)
async def get_job(job_id: UUID, db: Session = Depends(get_db)):
    """Get a specific job by ID."""
    job = (
        db.query(Job)
        .options(
            joinedload(Job.company),
            selectinload(Job.governed_job_skills).joinedload(GovernedJobSkill.skill),
            selectinload(Job.governed_skill_mentions).joinedload(
                GovernedJobSkillMention.candidate
            ),
            joinedload(Job.subcategory)
            .joinedload(JobSubcategory.category)
            .joinedload(JobCategory.domain),
            *_source_attribute_load_options(include_labels=True),
        )
        .filter(Job.id == job_id, Job.is_deleted.is_(False))
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    detail = JobDetailSchema.model_validate(job).model_dump(mode="python")
    try:
        skill_state = SkillGovernanceReader(db).get_job_state(job.id)
    except SkillGovernanceReadError as exc:
        if exc.code == "SKILL_TAXONOMY_NOT_ACTIVE":
            detail["skills"] = []
            detail["provisional_skills"] = []
            detail["unreviewed_skill_mentions"] = []
        else:
            raise HTTPException(status_code=409, detail=exc.to_detail()) from exc
    else:
        detail["skills"] = [skill.name for skill in skill_state.skills]
        detail["provisional_skills"] = [
            mention.raw_name for mention in skill_state.unreviewed_skill_mentions
        ]
        detail["unreviewed_skill_mentions"] = [
            mention.to_payload() for mention in skill_state.unreviewed_skill_mentions
        ]
    return JobDetailSchema.model_validate(detail)


@router.post("", response_model=JobSchema, deprecated=True)
async def create_job(
    _job: JobCreateSchema,
    _db: Session = Depends(get_db),
):
    """Reject the retired collected-Job bypass; use source ingestion or manual."""
    raise HTTPException(
        status_code=410,
        detail={
            "code": "COLLECTED_JOB_CREATE_RETIRED",
            "message": (
                "Collected Jobs must be written through a source ingestion path; "
                "use POST /api/v1/jobs/manual for manually entered Jobs."
            ),
        },
    )


@router.post("/manual", response_model=JobDetailSchema)
async def create_manual_job(
    job_data: ManualJobCreateSchema,
    db: Session = Depends(get_db),
):
    """Create a manually entered job and trigger AI enrichment."""
    try:
        ensure_profile_runtime_ready("jobs")
    except ProfileRuntimeNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Generate a unique job_id for manual jobs
    manual_job_id = f"manual:{uuid_lib.uuid4()}"

    # Build the job object
    db_job = Job(
        job_id=manual_job_id,
        source_site="manual",
        source_job_id=manual_job_id,
        company_id=job_data.company_id,
        title=job_data.title,
        description=job_data.description,
        salary_range=job_data.salary_range,
        salary_min=job_data.salary_min,
        salary_max=job_data.salary_max,
        salary_currency=job_data.salary_currency or "HKD",
        location=job_data.location,
        employment_type=job_data.employment_type,
        posted_date=job_data.posted_date,
        experience_min_years=job_data.experience_min_years,
        experience_max_years=job_data.experience_max_years,
    )
    db.add(db_job)
    db.flush()

    service = EnrichmentRunService(db)
    try:
        run = service.create_manual_job_run(str(db_job.id))
    except ActiveEnrichmentRunError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "active_run_exists", "run_id": exc.run_id},
        ) from exc
    _publish_run_request(db, service=service, run_id=run.id)

    # Wait for enrichment to complete
    await _wait_for_terminal_run(run.id)

    # Return enriched job snapshot with company + skills
    snapshot = _load_job_snapshot(db_job.id)
    return snapshot
