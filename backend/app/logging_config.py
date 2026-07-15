"""Centralized logging configuration for the backend."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit, urlunsplit


DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
NOISY_LOGGERS = (
    "httpcore",
    "httpx",
    "urllib3",
    "sqlalchemy.engine",
    "asyncio",
)
SUPPRESSED_ACCESS_PATHS = frozenset(
    {
        "/health",
    }
)
SCRAPER_LOGGER_NAMES = (
    "app.scraper",
    "app.sources",
    "app.workers.run_ingest_worker",
    "app.api.crawl_jobs",
    "app.services.crawl_job_dispatch_service",
)


def redact_url(url: str, *, redact_query: bool = False) -> str:
    """Mask URL credentials and optionally remove query/fragment values."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url

    if not parsed.scheme or not parsed.netloc:
        if redact_query and (parsed.query or parsed.fragment):
            return urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, "", "")
            )
        return url

    safe_netloc = parsed.netloc
    if "@" in parsed.netloc:
        auth, host = parsed.netloc.rsplit("@", 1)
        username = auth.split(":", 1)[0] if auth else ""
        safe_auth = f"{username}:***" if username else "***"
        safe_netloc = f"{safe_auth}@{host}"

    if safe_netloc == parsed.netloc and not redact_query:
        return url

    return urlunsplit(
        (
            parsed.scheme,
            safe_netloc,
            parsed.path,
            "" if redact_query else parsed.query,
            "" if redact_query else parsed.fragment,
        )
    )


def should_suppress_uvicorn_access_log(record: logging.LogRecord) -> bool:
    """Suppress frequent low-signal access logs that drown out debugging output."""
    if record.name != "uvicorn.access":
        return False

    args = getattr(record, "args", ())
    if not isinstance(args, tuple) or len(args) < 5:
        return False

    _client_addr, method, full_path, _http_version, _status_code = args[:5]
    if str(method).upper() != "GET":
        return False

    path = str(full_path).split("?", 1)[0]
    return path in SUPPRESSED_ACCESS_PATHS


class UvicornAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not should_suppress_uvicorn_access_log(record)


def _resolve_log_level(value: str | None, fallback: int) -> int:
    if not value:
        return fallback
    return getattr(logging, str(value).upper(), fallback)


def configure_logging(log_level: str, scraper_log_level: str | None = None) -> None:
    """Configure root logging once and keep third-party noise down."""
    level = _resolve_log_level(log_level, logging.INFO)
    scraper_level = _resolve_log_level(scraper_log_level, level)
    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)
    root_logger = logging.getLogger()

    if root_logger.handlers:
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    root_logger.setLevel(level)

    for logger_name in NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    for logger_name in SCRAPER_LOGGER_NAMES:
        logging.getLogger(logger_name).setLevel(scraper_level)

    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(existing_filter, UvicornAccessFilter) for existing_filter in access_logger.filters):
        access_logger.addFilter(UvicornAccessFilter())
