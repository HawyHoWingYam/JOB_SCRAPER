from fastapi import APIRouter

from app.api import companies, crawl_jobs, filters, health, jobs, recommendations, settings

router = APIRouter()

# Include route modules
router.include_router(health.router)
router.include_router(jobs.router, prefix="/api/v1")
router.include_router(companies.router, prefix="/api/v1")
router.include_router(crawl_jobs.router, prefix="/api/v1")
router.include_router(filters.router, prefix="/api/v1")
router.include_router(recommendations.router, prefix="/api/v1")
router.include_router(settings.router)

__all__ = ["router"]
