from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.host_manual_action_helper import HostManualActionHelperServer
from app.logging_config import configure_logging

configure_logging(settings.log_level, settings.scraper_log_level)
logger = logging.getLogger(__name__)


async def main() -> None:
    server = HostManualActionHelperServer(
        host=settings.manual_action_helper_host,
        port=settings.jobsdb_headed_manual_action_helper_port,
    )
    server.start()
    logger.info(
        "Manual action helper listening at http://%s:%s",
        settings.manual_action_helper_host,
        settings.jobsdb_headed_manual_action_helper_port,
    )
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        server.stop()


if __name__ == "__main__":
    asyncio.run(main())
