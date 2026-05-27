from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import socket
from urllib.parse import urlparse

from app.config import settings
from app.host_manual_action_helper import HostManualActionHelperServer
from app.logging_config import configure_logging
from app.messaging.topics import STREAM_CRAWL_COMMANDS_HEADED
from app.workers.run_crawl_worker import CrawlWorkerService

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


def _headed_runner_registry():
    from crawler.job_crawler.spiders.ctgoodjobs_headed_spider import CTGoodJobsHeadedSpider
    from crawler.job_crawler.spiders.jobsdb_headed_spider import JobsDBHeadedSpider

    return {
        "jobsdb": JobsDBHeadedSpider(),
        "ctgoodjobs": CTGoodJobsHeadedSpider(),
    }


def validate_host_runtime_settings(
    *,
    database_url: str,
    redis_url: str,
    browser_channel: str,
    browser_user_data_dir: str | None,
) -> dict[str, str]:
    db_host = (urlparse(database_url).hostname or "").strip().lower()
    redis_host = (urlparse(redis_url).hostname or "").strip().lower()

    if db_host in {"postgres-db", "postgres", "db"}:
        raise RuntimeError("DATABASE_URL must point to a host-reachable address, not a Docker-only hostname")
    if redis_host in {"redis-mq", "redis"}:
        raise RuntimeError("REDIS_URL must point to a host-reachable address, not a Docker-only hostname")
    if db_host not in {"localhost", "127.0.0.1"}:
        raise RuntimeError(f"DATABASE_URL must use localhost/127.0.0.1 for host-side worker startup (got {db_host or 'unknown'})")
    if redis_host not in {"localhost", "127.0.0.1"}:
        raise RuntimeError(f"REDIS_URL must use localhost/127.0.0.1 for host-side worker startup (got {redis_host or 'unknown'})")

    if not browser_user_data_dir:
        raise RuntimeError("JOBSDB_HEADED_BROWSER_USER_DATA_DIR must be set for host-side headed startup")

    profile_path = Path(browser_user_data_dir)
    if not profile_path.exists():
        raise RuntimeError(f"JobsDB headed browser profile directory does not exist: {profile_path}")

    return {
        "database_url": database_url,
        "redis_url": redis_url,
        "browser_channel": browser_channel,
        "browser_user_data_dir": str(profile_path),
    }


def acquire_single_instance_lock(*, port: int) -> socket.socket:
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock_socket.bind(("127.0.0.1", int(port)))
        lock_socket.listen(1)
    except OSError as exc:
        lock_socket.close()
        raise RuntimeError(
            f"Headed crawl worker is already running or lock port {port} is unavailable"
        ) from exc
    return lock_socket


async def main() -> None:
    runtime_info = validate_host_runtime_settings(
        database_url=settings.database_url,
        redis_url=settings.redis_url,
        browser_channel=settings.jobsdb_headed_browser_channel,
        browser_user_data_dir=settings.jobsdb_headed_browser_user_data_dir,
    )
    lock_socket = acquire_single_instance_lock(
        port=settings.jobsdb_headed_worker_lock_port,
    )
    logger.info("Starting headed crawl worker")
    logger.info("Headed worker database: %s", runtime_info["database_url"])
    logger.info("Headed worker redis: %s", runtime_info["redis_url"])
    logger.info("Headed worker browser channel: %s", runtime_info["browser_channel"])
    logger.info("Headed worker browser profile: %s", runtime_info["browser_user_data_dir"])
    logger.info("Headed worker lock port: %s", settings.jobsdb_headed_worker_lock_port)
    helper_server = HostManualActionHelperServer(
        port=settings.jobsdb_headed_manual_action_helper_port,
    )
    helper_server.start()
    logger.info("Headed worker manual-action helper: http://127.0.0.1:%s", settings.jobsdb_headed_manual_action_helper_port)
    service = CrawlWorkerService(
        group_name="crawl-headed-workers",
        consumer_name="crawl-headed-worker",
        command_topic=STREAM_CRAWL_COMMANDS_HEADED,
        runner_registry=_headed_runner_registry(),
    )
    try:
        while True:
            processed = await service.run_once()
            if processed == 0:
                await asyncio.sleep(1.0)
    finally:
        helper_server.stop()
        lock_socket.close()


if __name__ == "__main__":
    asyncio.run(main())
