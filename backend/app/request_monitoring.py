from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

REQUEST_ID_HEADER = "X-Request-ID"
SLOW_REQUEST_THRESHOLD_MS = 1000
IMPORTANT_REQUEST_PATH_PREFIXES = (
    "/api/v1/crawl-jobs",
    "/api/v1/scrape/progress",
    "/api/v1/schedules",
)

logger = logging.getLogger("app.request_monitoring")


def build_monitoring_log_event(event: str, **fields: object) -> str:
    parts = [str(event).strip()]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={str(value).replace(chr(10), '\\n')}")
    return " ".join(parts)


def create_request_id() -> str:
    return f"req-{uuid4().hex}"


def should_log_request_summary(*, path: str, status_code: int, duration_ms: int) -> bool:
    if status_code >= 500 or duration_ms >= SLOW_REQUEST_THRESHOLD_MS:
        return True
    return any(path.startswith(prefix) for prefix in IMPORTANT_REQUEST_PATH_PREFIXES)


def log_request_summary(*, request: Request, request_id: str, status_code: int, duration_ms: int) -> None:
    if should_log_request_summary(
        path=request.url.path,
        status_code=status_code,
        duration_ms=duration_ms,
    ):
        logger.info(
            build_monitoring_log_event(
                "API_REQUEST_SUMMARY",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status=status_code,
                duration_ms=duration_ms,
            )
        )


def install_request_monitoring(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_monitoring_middleware(request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or create_request_id()
        request.state.request_id = request_id
        started_at = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.exception(
                build_monitoring_log_event(
                    "API_REQUEST_EXCEPTION",
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    duration_ms=duration_ms,
                )
            )
            response = PlainTextResponse("Internal Server Error", status_code=500)
            response.headers[REQUEST_ID_HEADER] = request_id
            log_request_summary(
                request=request,
                request_id=request_id,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response

        response.headers[REQUEST_ID_HEADER] = request_id
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        log_request_summary(
            request=request,
            request_id=request_id,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
