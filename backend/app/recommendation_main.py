from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.api.internal_recommendations import router as recommendations_router
from app.config import settings
from app.logging_config import configure_logging, redact_url
from app.server_runtime import run_api_app

configure_logging(settings.log_level, settings.scraper_log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting recommendation API")
    logger.info("Database: %s", redact_url(settings.database_url))
    try:
        yield
    finally:
        logger.info("Shutting down recommendation API")


app = FastAPI(
    title="JobsDB Recommendation API",
    description="Internal job recommendation service",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.include_router(recommendations_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "recommendation-api"}


def main() -> None:
    run_api_app("app.recommendation_main:app", settings_obj=settings)


if __name__ == "__main__":
    main()
