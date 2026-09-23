from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlsplit, urlunsplit

from app.config import settings
from app.logging_config import configure_logging

configure_logging(settings.log_level, settings.scraper_log_level)
logger = logging.getLogger(__name__)

_DOCKER_DATABASE_HOSTS = frozenset({"postgres-db"})
_HOST_DATABASE_OVERRIDE_ENV = "MANUAL_ACTION_HELPER_DATABASE_URL"


def resolve_host_database_url(database_url: str) -> str:
    """Make the Docker PostgreSQL hostname reachable from the host helper.

    The API container uses ``postgres-db:5432`` on the Compose network, while
    this helper runs directly on macOS/Linux and reaches the published port on
    ``127.0.0.1:5433``. An explicit helper-only URL always wins, and any other
    database URL is left unchanged for remote/custom deployments.
    """

    override = os.environ.get(_HOST_DATABASE_OVERRIDE_ENV, "").strip()
    if override:
        return override

    parsed = urlsplit(database_url)
    if (parsed.hostname or "").lower() not in _DOCKER_DATABASE_HOSTS:
        return database_url

    user_info, separator, _host = parsed.netloc.rpartition("@")
    prefix = f"{user_info}{separator}" if separator else ""
    return urlunsplit(parsed._replace(netloc=f"{prefix}127.0.0.1:5433"))


def _configure_host_database() -> None:
    original_url = settings.database_url
    resolved_url = resolve_host_database_url(original_url)
    settings.database_url = resolved_url
    if resolved_url != original_url:
        logger.info(
            "Translated Docker database hostname for host helper "
            "(host=127.0.0.1 port=5433)"
        )


async def main() -> None:
    _configure_host_database()
    # Import after database configuration: app.database creates the SQLAlchemy
    # engine at import time and must use the host-reachable URL.
    from app.host_manual_action_helper import HostManualActionHelperServer

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
