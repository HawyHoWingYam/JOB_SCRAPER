"""
JobsDB Scraper - FastAPI Backend Application
Main entry point for the backend API service.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from app.config import settings
from app.api import router
from app.api.category_routes import router as category_router
from app.api.schedules import router as schedules_router
from app.api.progress import router as progress_router
from app.api.ai import router as ai_router
from app.api.stats import router as stats_router
from app.api.skills import router as skills_router
from app.logging_config import configure_logging, redact_url
from app.database import SessionLocal
from app.server_runtime import run_api_app
from app.services.startup_recovery_service import StartupRecoveryService

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


def run_api_startup_recovery() -> dict[str, int]:
    startup_db = SessionLocal()
    try:
        summary = StartupRecoveryService(startup_db).recover_interrupted_operations(
            recover_ai_runs=False,
            recover_company_runs=True,
            recover_crawl_jobs=True,
            recover_schedule_executions=True,
        )
        startup_db.commit()
        return summary
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
app.include_router(schedules_router, prefix="/api/v1")
app.include_router(progress_router, prefix="/api/v1")
app.include_router(ai_router)
app.include_router(stats_router)
app.include_router(skills_router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "JobsDB Scraper API",
        "version": "0.1.0",
        "docs": "/docs",
    }


def main() -> None:
    run_api_app("app.main:app", settings_obj=settings)


if __name__ == "__main__":
    main()
