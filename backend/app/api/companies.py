from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import SessionLocal, get_db
from app.models import Company
from app.schemas import CompanySchema, CompanyCreateSchema
from app.services.company_enrichment_service import CompanyEnrichmentService
from app.services.company_enrichment_run_service import CompanyEnrichmentRunService
from app.services.ai_runtime_settings_service import ensure_profile_runtime_ready, ProfileRuntimeNotReadyError

router = APIRouter(prefix="/companies", tags=["companies"])


class CompanyListResponse(BaseModel):
    """Paginated company listing response."""

    items: list[CompanySchema]
    total: int
    page: int
    page_size: int
    total_pages: int


class CompanyEnrichmentRunSchema(BaseModel):
    """Serialized company enrichment run response."""

    id: str
    status: str
    total_items: int
    pending_items: int
    completed_items: int
    failed_items: int
    started_at: str | None = None
    completed_at: str | None = None
    current_company_name: str | None = None
    error_message: str | None = None
    created_at: str | None = None


class CompanyEnrichmentResult(BaseModel):
    """Minimal response for company enrichment actions."""

    model_config = ConfigDict(from_attributes=True)

    company_id: UUID
    ai_description: str


class CompanyBatchEnrichmentRequest(BaseModel):
    """Request payload for batch company description enrichment."""

    company_ids: list[UUID] = Field(..., min_length=1, max_length=50)


class CompanyBatchEnrichmentResponse(BaseModel):
    """Response payload for batch company enrichment."""

    processed_count: int
    companies: list[CompanyEnrichmentResult]


def _serialize_run(run) -> dict:
    return {
        "id": run.id,
        "status": run.status,
        "total_items": run.total_items,
        "pending_items": run.pending_items,
        "completed_items": run.completed_items,
        "failed_items": run.failed_items,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "current_company_name": run.current_company_name,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


async def _run_persisted_company_enrichment(run_id: str) -> None:
    db = SessionLocal()
    try:
        await CompanyEnrichmentRunService(db).execute_run(run_id)
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            CompanyEnrichmentRunService(db).mark_run_failed(run_id, str(exc))
            db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


@router.post("/enrichment-runs")
async def create_company_enrichment_run(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Create or resume a persisted company enrichment run."""
    try:
        ensure_profile_runtime_ready("companies")
    except ProfileRuntimeNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    service = CompanyEnrichmentRunService(db)
    active_run = service.get_active_run()
    if active_run is not None:
        return _serialize_run(active_run)

    run = service.create_pending_run()
    if run is None:
        return {"status": "empty", "run": None}

    run_id = run.id
    db.commit()
    background_tasks.add_task(_run_persisted_company_enrichment, run_id)
    db.refresh(run)
    return _serialize_run(run)


@router.get("/enrichment-runs/current")
async def get_current_company_enrichment_run(db: Session = Depends(get_db)):
    """Return the active company enrichment run or latest terminal run."""
    run = CompanyEnrichmentRunService(db).get_current_run()
    if run is None:
        return None
    return _serialize_run(run)


@router.get("/enrichment-runs/{run_id}")
async def get_company_enrichment_run(run_id: str, db: Session = Depends(get_db)):
    """Get a specific company enrichment run."""
    run = CompanyEnrichmentRunService(db).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize_run(run)


@router.get("/enrichment-runs/{run_id}/items")
async def get_company_enrichment_run_items(run_id: str, db: Session = Depends(get_db)):
    """Get item rows for a company enrichment run."""
    service = CompanyEnrichmentRunService(db)
    run = service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "items": [
            {
                "id": item.id,
                "run_id": item.run_id,
                "company_id": str(item.company_id),
                "position": item.position,
                "status": item.status,
                "error_message": item.error_message,
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in service.list_run_items(run_id)
        ]
    }


@router.get("", response_model=CompanyListResponse)
async def list_companies(
    q: str | None = Query(None),
    status: str = Query("pending"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List all companies with pagination."""
    ai_missing_clause = or_(Company.ai_description.is_(None), Company.ai_description == "")
    query = db.query(Company).filter(Company.is_deleted == False)
    if q:
        query = query.filter(Company.name.ilike(f"%{q}%"))
    if status == "pending":
        query = query.filter(ai_missing_clause)
    elif status == "ready":
        query = query.filter(~ai_missing_clause)
    elif status != "all":
        raise HTTPException(status_code=422, detail="Unsupported company status filter")

    sort_pending_first = case((ai_missing_clause, 0), else_=1)
    companies = (
        query.order_by(sort_pending_first.asc(), Company.created_at.desc(), Company.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    current_offset = (page - 1) * page_size
    if len(companies) < page_size:
        total = current_offset + len(companies)
        total_pages = page if total else 0
    else:
        total = query.count()
        total_pages = (total + page_size - 1) // page_size if total else 0

    return {
        "items": companies,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/{company_id}", response_model=CompanySchema)
async def get_company(company_id: UUID, db: Session = Depends(get_db)):
    """Get a specific company by ID."""
    company = db.query(Company).filter(
        Company.id == company_id, Company.is_deleted == False
    ).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.post("", response_model=CompanySchema)
async def create_company(company: CompanyCreateSchema, db: Session = Depends(get_db)):
    """Create a new company."""
    # Check if company already exists
    existing = db.query(Company).filter(
        Company.company_id == company.company_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Company already exists")

    db_company = Company(**company.dict())
    db.add(db_company)
    db.commit()
    db.refresh(db_company)
    return db_company


@router.post("/{company_id}/enrich-description")
async def enrich_company_description(
    company_id: UUID,
    force: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Generate a concise AI description for a company."""
    try:
        ensure_profile_runtime_ready("companies")
    except ProfileRuntimeNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    company = db.query(Company).filter(
        Company.id == company_id,
        Company.is_deleted == False,
    ).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return await CompanyEnrichmentService().enrich_company_description(company, db, force=force)


@router.post("/enrich-descriptions", response_model=CompanyBatchEnrichmentResponse)
async def batch_enrich_company_descriptions(
    payload: CompanyBatchEnrichmentRequest = Body(...),
    db: Session = Depends(get_db),
):
    """Generate concise AI descriptions for multiple companies in a single request."""
    try:
        ensure_profile_runtime_ready("companies")
    except ProfileRuntimeNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    requested_ids = payload.company_ids
    companies = (
        db.query(Company)
        .filter(
            Company.id.in_(requested_ids),
            Company.is_deleted == False,
        )
        .all()
    )
    company_map = {company.id: company for company in companies}
    ordered_companies = [company_map[company_id] for company_id in requested_ids if company_id in company_map]

    if len(ordered_companies) != len(requested_ids):
        raise HTTPException(status_code=404, detail="One or more companies were not found")

    pending_companies = [
        company
        for company in ordered_companies
        if not (company.ai_description or "").strip()
    ]

    return await CompanyEnrichmentService().enrich_company_descriptions(pending_companies, db)
