from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.jobs import JobSearchResponse, _summarize_layer, _validate_scope_expressions
from app.database import get_db
from app.schemas.job_search import JobSearchRequestSchema
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/internal/jobs", tags=["retrieval"])


@router.post("/search", response_model=JobSearchResponse)
async def search_jobs_internal(
    request: JobSearchRequestSchema,
    db: Session = Depends(get_db),
):
    _validate_scope_expressions(request)
    return RetrievalService(db).search(
        request,
        layer_summaries=[_summarize_layer(layer) for layer in request.scope.layers],
    )
