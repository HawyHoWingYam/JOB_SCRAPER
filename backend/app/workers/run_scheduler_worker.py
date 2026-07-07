from __future__ import annotations

import asyncio
import logging

from app.logging_config import configure_logging
from app.config import settings
from app.services.scheduler_runtime import initialize_scheduler_runtime, shutdown_scheduler_runtime

configure_logging(settings.log_level, settings.scraper_log_level)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Starting scheduler worker")
    await initialize_scheduler_runtime()
    try:
        await asyncio.Event().wait()
    finally:
        shutdown_scheduler_runtime()


if __name__ == "__main__":
    asyncio.run(main())
