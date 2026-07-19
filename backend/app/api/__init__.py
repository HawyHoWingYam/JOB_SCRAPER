from fastapi import APIRouter

from app.api import (
    capabilities,
    company_industries,
    companies,
    crawl_jobs,
    filters,
    health,
    job_intelligence,
    jobs,
    recommendations,
    settings,
    skill_governance,
    skills,
)

router = APIRouter()

# Include route modules
router.include_router(health.router)
router.include_router(job_intelligence.router, prefix="/api/v1")
router.include_router(company_industries.router, prefix="/api/v1")
router.include_router(skill_governance.router, prefix="/api/v1")
router.include_router(skills.router, prefix="/api/v1")
router.include_router(jobs.router, prefix="/api/v1")
router.include_router(companies.router, prefix="/api/v1")
router.include_router(crawl_jobs.router, prefix="/api/v1")
router.include_router(filters.router, prefix="/api/v1")
router.include_router(recommendations.router, prefix="/api/v1")
router.include_router(capabilities.router, prefix="/api/v1")
router.include_router(settings.router)

__all__ = ["router"]
