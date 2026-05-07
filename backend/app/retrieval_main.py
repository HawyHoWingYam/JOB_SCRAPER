from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.api.retrieval import router as retrieval_router
from app.config import settings
from app.logging_config import configure_logging, redact_url

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting retrieval API")
    logger.info("Database: %s", redact_url(settings.database_url))
    try:
        yield
    finally:
        logger.info("Shutting down retrieval API")


app = FastAPI(
    title="JobsDB Retrieval API",
    description="Internal semantic and hybrid retrieval service",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.include_router(retrieval_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "retrieval-api"}
