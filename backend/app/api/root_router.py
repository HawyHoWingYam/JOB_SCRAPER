from fastapi import APIRouter

from app.api import (
    capabilities,
    companies,
    crawl_control,
    crawl_jobs,
    filters,
    health,
    current_taxonomies,
    jobs,
    recommendations,
    offertoday_keyword_packs,
    settings,
    skills,
)

router = APIRouter()

router.include_router(health.router)
router.include_router(current_taxonomies.router, prefix="/api")
router.include_router(skills.router, prefix="/api")
router.include_router(jobs.router, prefix="/api")
router.include_router(companies.router, prefix="/api")
router.include_router(crawl_control.router, prefix="/api")
router.include_router(crawl_jobs.router, prefix="/api")
router.include_router(filters.router, prefix="/api")
router.include_router(recommendations.router, prefix="/api")
router.include_router(offertoday_keyword_packs.router, prefix="/api")
router.include_router(capabilities.router, prefix="/api")
router.include_router(settings.router)

__all__ = ["router"]
