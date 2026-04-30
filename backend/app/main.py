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
from app.services.scheduler_service import SchedulerService

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run application startup and shutdown lifecycle."""
    logger.info("Starting JobsDB Scraper API")
    logger.info("Debug mode: %s", settings.debug)
    logger.info("Database: %s", redact_url(settings.database_url))

    scheduler = SchedulerService.get_instance()
    await scheduler.initialize()

    try:
        yield
    finally:
        logger.info("Shutting down JobsDB Scraper API")
        scheduler.shutdown()

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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
