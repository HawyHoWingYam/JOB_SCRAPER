import re
import csv
import html
import json
from datetime import date
from io import StringIO
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, false, func, not_, or_
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from app.database import get_db
from app.api.job_search_parser import parse_search_expression, SearchExpressionError
from app.api.job_search_query import apply_parsed_clauses
from app.models import Job, Company
from app.models.skill import Skill
from app.models.job_skill import JobSkill
from app.models import SkillTechnology, JobSubcategory, JobCategory, JobDomain
from app.schemas import JobSchema, JobCreateSchema, JobDetailSchema
from app.schemas.job_search import (
    JobSearchRequestSchema,
    JobSearchFiltersSchema,
    JobSearchLayerSchema,
    JobSearchScopeSchema,
    JobSearchLayerSummarySchema,
)
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
    ai_category: Optional[str] = None
    subcategory_id: Optional[UUID] = None
    company_name: Optional[str] = None
    posted_date: Optional[str] = None

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


class FilterOptionsResponse(BaseModel):
    """Available filter options."""
    locations: List[str]
    regions: List[str]
    location_hierarchy: List[LocationHierarchyItem]
    employment_types: List[str]
    categories: List[str]
    industries: List[str]


def _build_location_hierarchy(raw_locations: List[str]) -> List[LocationHierarchyItem]:
    districts_by_region = {region: set() for region in REGION_ORDER}

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
        _location_matches_district(column, district)
        for district in DISTRICT_TO_REGION
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


def _parse_legacy_category_path(category: str) -> Optional[tuple[str, str, str]]:
    parts = [part.strip() for part in (category or "").split(" / ")]
    if len(parts) != 3 or not all(parts):
        return None
    return parts[0], parts[1], parts[2]


def _build_legacy_category_filter_clause(category: str):
    canonical_path = _parse_legacy_category_path(category)
    if canonical_path is None:
        return Job.ai_category == category

    domain_name, category_name, subcategory_name = canonical_path
    return or_(
        Job.subcategory.has(
            and_(
                JobSubcategory.name == subcategory_name,
                JobSubcategory.category.has(
                    and_(
                        JobCategory.name == category_name,
                        JobCategory.domain.has(JobDomain.name == domain_name),
                    )
                ),
            )
        ),
        and_(
            Job.subcategory_id.is_(None),
            Job.ai_category == category,
        ),
    )


def _apply_structured_filters(query, filters: JobSearchFiltersSchema):
    _validate_experience_query_window(
        filters.experience_years_from,
        filters.experience_years_to,
    )

    if filters.location and not filters.region and not filters.district:
        query = query.filter(Job.location.ilike(f"%{filters.location}%"))
    if filters.employment_type:
        query = query.filter(Job.employment_type == filters.employment_type)
    if filters.category:
        query = query.filter(_build_legacy_category_filter_clause(filters.category))
    if filters.industry:
        query = query.filter(Company.industry == filters.industry)
    if filters.posted_date_from:
        query = query.filter(func.date(Job.posted_date) >= filters.posted_date_from)
    if filters.posted_date_to:
        query = query.filter(func.date(Job.posted_date) <= filters.posted_date_to)
    if filters.experience_years_from is not None or filters.experience_years_to is not None:
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

    if filters.skill_ids:
        query = query.join(JobSkill).filter(JobSkill.skill_id.in_(filters.skill_ids)).distinct()
    elif filters.technology_ids:
        query = query.join(JobSkill).join(Skill).filter(Skill.technology_id.in_(filters.technology_ids)).distinct()
    elif filters.skill_category_ids:
        query = query.join(JobSkill).join(Skill).join(SkillTechnology).filter(
            SkillTechnology.category_id.in_(filters.skill_category_ids)
        ).distinct()
    elif filters.skills:
        query = query.join(JobSkill).join(Skill).filter(Skill.name.in_(filters.skills)).distinct()

    if filters.subcategory_ids:
        query = query.filter(Job.subcategory_id.in_(filters.subcategory_ids))
    elif filters.job_category_ids:
        query = query.join(JobSubcategory).filter(JobSubcategory.category_id.in_(filters.job_category_ids))
    elif filters.domain_ids:
        query = query.join(JobSubcategory).join(JobCategory).filter(JobCategory.domain_id.in_(filters.domain_ids))

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
    if filters.industry:
        parts.append(f"Industry: {filters.industry}")
    if filters.category:
        parts.append(f"AI category: {filters.category}")
    if filters.employment_type:
        parts.append(f"Job type: {filters.employment_type}")

    return JobSearchLayerSummarySchema(
        client_id=layer.client_id,
        label=" | ".join(parts) if parts else "Structured filters only",
    )


def _build_query_from_scope(db: Session, scope: JobSearchScopeSchema):
    query = db.query(Job, Company).join(
        Company, Job.company_id == Company.id
    ).filter(Job.is_deleted.is_(False)).options(
        joinedload(Job.job_skills).joinedload(JobSkill.skill),
        joinedload(Job.company),
    )

    for layer in scope.layers:
        query = apply_parsed_clauses(query, parse_search_expression(layer.text_expression))
        query = _apply_structured_filters(query, layer.structured_filters)

    return query


def _build_legacy_scope(
    *,
    q: Optional[str],
    location: Optional[str],
    region: Optional[str],
    district: Optional[str],
    employment_type: Optional[str],
    category: Optional[str],
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
                    location=location,
                    region=region,
                    district=district,
                    employment_type=employment_type,
                    category=category,
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
):
    offset = (page - 1) * page_size
    total = query.order_by(None).count()
    results = (
        query
        .order_by(Job.posted_date.desc().nullslast())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    jobs = []
    for job, company in results:
        jobs.append(JobWithCompanySchema(
            id=job.id,
            job_id=job.job_id,
            title=job.title,
            description=job.description[:200] + "..." if job.description and len(job.description) > 200 else job.description,
            location=job.location,
            salary_range=job.salary_range,
            employment_type=job.employment_type,
            ai_category=job.ai_category,
            subcategory_id=job.subcategory_id,
            company_name=company.name if company else None,
            posted_date=job.posted_date.isoformat() if job.posted_date else None
        ))

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
    return job_id[len(prefix):] if job_id.startswith(prefix) else job_id


def _build_original_job_url(job) -> str:
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
                "is_expired": "" if job.is_expired is None else str(job.is_expired).lower(),
                "salary_range": job.salary_range or "",
                "salary_min": "" if job.salary_min is None else str(job.salary_min),
                "salary_max": "" if job.salary_max is None else str(job.salary_max),
                "salary_currency": job.salary_currency or "",
                "source_classification_name": job.source_classification_name or "",
                "source_subclassification_name": job.source_subclassification_name or "",
                "ai_category": job.ai_category or "",
                "ai_summary": job.ai_summary or "",
                "experience_level": job.experience_level or "",
                "experience_min_years": "" if job.experience_min_years is None else str(job.experience_min_years),
                "experience_max_years": "" if job.experience_max_years is None else str(job.experience_max_years),
                "experience_summary": job.experience_summary or "",
                "skills": " | ".join(job.skills),
                "company_ai_description": company.ai_description if company else "",
                "description_text": _strip_html_text(job.description),
            }
        )
    return rows


@router.get("", response_model=list[JobSchema])
async def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List all jobs with pagination."""
    jobs = db.query(Job).filter(Job.is_deleted.is_(False)).offset(skip).limit(limit).all()
    return jobs


@router.get("/search", response_model=JobSearchResponse)
async def search_jobs(
    q: Optional[str] = Query(None, description="Full-text search query"),
    location: Optional[str] = Query(None, description="Filter by location"),
    region: Optional[str] = Query(None, description="Filter by normalized region"),
    district: Optional[str] = Query(None, description="Filter by normalized district"),
    employment_type: Optional[str] = Query(None, description="Filter by employment type"),
    category: Optional[str] = Query(None, description="Filter by AI category"),
    industry: Optional[str] = Query(None, description="Filter by industry"),
    posted_date_from: Optional[date] = Query(None, description="Filter by posted date from"),
    posted_date_to: Optional[date] = Query(None, description="Filter by posted date to"),
    experience_years_from: Optional[int] = Query(None, ge=0, description="Filter by minimum required experience years"),
    experience_years_to: Optional[int] = Query(None, ge=0, description="Filter by maximum required experience years"),
    skills: Optional[List[str]] = Query(None, description="Filter by skills"),
    skill_ids: Optional[List[str]] = Query(None, description="Filter by skill IDs (L3)"),
    technology_ids: Optional[List[str]] = Query(None, description="Filter by technology IDs (L2)"),
    skill_category_ids: Optional[List[str]] = Query(None, description="Filter by skill category IDs (L1)"),
    subcategory_ids: Optional[List[str]] = Query(None, description="Filter by job subcategory IDs (L3)"),
    job_category_ids: Optional[List[str]] = Query(None, description="Filter by job category IDs (L2)"),
    domain_ids: Optional[List[str]] = Query(None, description="Filter by job domain IDs (L1)"),
    salary_min: Optional[int] = Query(None, ge=0, description="Minimum salary (HKD)"),
    salary_max: Optional[int] = Query(None, ge=0, description="Maximum salary (HKD)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
):
    """Search jobs with filters and pagination."""
    scope = _build_legacy_scope(
        q=q,
        location=location,
        region=region,
        district=district,
        employment_type=employment_type,
        category=category,
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

    query = _build_query_from_scope(db, request.scope)
    return _build_search_response(
        query,
        page=request.page,
        page_size=request.page_size,
        applied_scope=request.scope,
        layer_summaries=[_summarize_layer(layer) for layer in request.scope.layers],
    )


@router.post("/search/export")
async def export_jobs_search_scope(
    request: JobSearchRequestSchema,
    db: Session = Depends(get_db),
):
    _validate_scope_expressions(request)

    query = _build_query_from_scope(db, request.scope)
    total = query.order_by(None).count()
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

    rows = _build_export_rows(query)
    fieldnames = [
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
        "ai_category",
        "ai_summary",
        "experience_level",
        "experience_min_years",
        "experience_max_years",
        "experience_summary",
        "skills",
        "company_ai_description",
        "description_text",
    ]

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="job-search-export.csv"',
        },
    )


@router.get("/filters", response_model=FilterOptionsResponse)
async def get_filter_options(db: Session = Depends(get_db)):
    """Get available filter options from existing jobs."""
    # Get unique locations
    locations = db.query(Job.location).filter(
        Job.is_deleted.is_(False),
        Job.location.isnot(None),
        Job.location != ""
    ).distinct().all()

    # Get unique employment types
    employment_types = db.query(Job.employment_type).filter(
        Job.is_deleted.is_(False),
        Job.employment_type.isnot(None),
        Job.employment_type != ""
    ).distinct().all()

    # Get unique categories
    categories = db.query(Job.ai_category).filter(
        Job.is_deleted.is_(False),
        Job.ai_category.isnot(None),
        Job.ai_category != ""
    ).distinct().all()

    # Get unique industries from companies
    industries = db.query(Company.industry).filter(
        Company.is_deleted.is_(False),
        Company.industry.isnot(None),
        Company.industry != ""
    ).distinct().all()

    raw_locations = [loc[0] for loc in locations if loc[0]]

    return FilterOptionsResponse(
        locations=raw_locations,
        regions=REGION_ORDER,
        location_hierarchy=_build_location_hierarchy(raw_locations),
        employment_types=[et[0] for et in employment_types if et[0]],
        categories=[cat[0] for cat in categories if cat[0]],
        industries=[ind[0] for ind in industries if ind[0]]
    )


@router.get("/{job_id}", response_model=JobDetailSchema)
async def get_job(job_id: UUID, db: Session = Depends(get_db)):
    """Get a specific job by ID."""
    job = (
        db.query(Job)
        .options(
            joinedload(Job.company),
            joinedload(Job.job_skills).joinedload(JobSkill.skill),
        )
        .filter(Job.id == job_id, Job.is_deleted.is_(False))
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("", response_model=JobSchema)
async def create_job(job: JobCreateSchema, db: Session = Depends(get_db)):
    """Create a new job."""
    existing = db.query(Job).filter(Job.job_id == job.job_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Job already exists")

    db_job = Job(**job.dict())
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    return db_job
