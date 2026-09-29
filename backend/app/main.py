"""
JobsDB Scraper - FastAPI Backend Application
Main entry point for the backend API service.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import router
from app.api.category_routes import router as category_router
from app.api.crawl_admin import router as crawl_admin_router
from app.api.source_classifications import router as source_classification_router
from app.api.progress import router as progress_router
from app.api.ai import router as ai_router
from app.api.stats import router as stats_router
from app.api.skills import router as skills_router
from app.logging_config import configure_logging, redact_url
from app.database import SessionLocal
from app.request_monitoring import install_request_monitoring
from app.server_runtime import run_api_app
from app.services.startup_recovery_service import StartupRecoveryService
from app.services.crawl_job_execution_launcher import CrawlJobExecutionLauncher
from app.services.source_classification_registry import (
    build_source_classification_adapters,
    synchronize_source_classification_adapters,
)
from app.services.offertoday_keyword_catalog import OfferTodayKeywordCatalog
from app.services.offertoday_taxonomy_resolver import OfferTodayTaxonomyResolver
from app.services.skill_taxonomy_bootstrap import synchronize_initial_skill_taxonomy

configure_logging(settings.log_level, settings.scraper_log_level)
logger = logging.getLogger(__name__)


def run_api_startup_recovery() -> dict[str, int]:
    execution_launcher = CrawlJobExecutionLauncher()
    stale_executions_recovered = execution_launcher.recover_stale_executions()
    startup_db = SessionLocal()
    try:
        summary = StartupRecoveryService(startup_db).recover_interrupted_operations(
            recover_ai_runs=False,
            recover_company_runs=True,
            recover_crawl_jobs=True,
            recover_schedule_executions=True,
        )
        startup_db.commit()
        summary[
            "crawl_cancellations_supervised"
        ] = execution_launcher.recover_pending_cancellations()
        summary["stale_crawl_executions_recovered"] = stale_executions_recovered
        return summary
    finally:
        startup_db.close()


def synchronize_source_classifications_on_startup() -> dict[str, object]:
    startup_db = SessionLocal()
    try:
        adapters = build_source_classification_adapters()
        results = synchronize_source_classification_adapters(
            startup_db,
            (
                adapter
                for source_site, adapter in adapters.items()
                if source_site != "offertoday"
            ),
        )
        try:
            taxonomy = OfferTodayTaxonomyResolver(
                startup_db,
                adapter=adapters["offertoday"],
            ).refresh_or_last_verified(refresh=True)
            results["offertoday"] = {
                "freshness": taxonomy.freshness,
                "fingerprint": taxonomy.fingerprint,
            }
            OfferTodayKeywordCatalog(startup_db).bootstrap_initial_it_pack()
        except Exception as exc:
            results["offertoday"] = type(exc).__name__
        startup_db.commit()
        return results
    finally:
        startup_db.close()


def synchronize_skill_taxonomy_on_startup() -> dict[str, int | bool]:
    startup_db = SessionLocal()
    try:
        result = synchronize_initial_skill_taxonomy(startup_db)
        startup_db.commit()
        return result
    finally:
        startup_db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run application startup and shutdown lifecycle."""
    logger.info("Starting JobsDB Scraper API")
    logger.info("Debug mode: %s", settings.debug)
    logger.info("Database: %s", redact_url(settings.database_url))

    try:
        recovery_summary = run_api_startup_recovery()
        logger.info("Startup recovery summary: %s", recovery_summary)
    except Exception:
        logger.exception("Startup recovery sweep failed")

    try:
        classification_summary = await asyncio.to_thread(
            synchronize_source_classifications_on_startup
        )
        logger.info("Source classification sync summary: %s", classification_summary)
    except Exception:
        logger.exception("Source classification startup sync failed")

    try:
        skill_taxonomy_summary = await asyncio.to_thread(
            synchronize_skill_taxonomy_on_startup
        )
        logger.info("Skill taxonomy startup summary: %s", skill_taxonomy_summary)
    except Exception:
        logger.exception("Skill taxonomy startup sync failed")

    try:
        yield
    finally:
        logger.info("Shutting down JobsDB Scraper API")


# Initialize FastAPI application
app = FastAPI(
    title="JobsDB Scraper API",
    description="Backend API for JobsDB scraper with AI enrichment",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS
cors_origins = settings.cors_origins.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)
app.include_router(category_router, prefix="/api")
app.include_router(progress_router, prefix="/api")
app.include_router(ai_router)
app.include_router(stats_router)
app.include_router(skills_router, prefix="/api")
app.include_router(crawl_admin_router, prefix="/api")
app.include_router(source_classification_router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "JobsDB Scraper API",
        "docs": "/docs",
    }


asgi_app = install_request_monitoring(app)


def main() -> None:
    run_api_app("app.main:asgi_app", settings_obj=settings)


if __name__ == "__main__":
    main()
