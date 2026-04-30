from fastapi import APIRouter
from app.api import health, jobs, companies, filters

router = APIRouter()

# Include route modules
router.include_router(health.router)
router.include_router(jobs.router, prefix="/api/v1")
router.include_router(companies.router, prefix="/api/v1")
router.include_router(filters.router, prefix="/api/v1")

__all__ = ["router"]
