from __future__ import annotations

import logging
import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
SLOW_REQUEST_THRESHOLD_MS = 1000
IMPORTANT_REQUEST_PATH_PREFIXES = (
    "/api/v1/crawl-jobs",
    "/api/v1/scrape/progress",
    "/api/v1/schedules",
    "/api/v1/source-catalogs",
)
EXCLUDED_REQUEST_SUMMARY_PATHS = {"/api/v1/scrape/progress/stream"}

logger = logging.getLogger("app.request_monitoring")


def format_monitoring_log_value(value: object) -> str:
    text = str(value)
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    needs_quotes = text == "" or any(char.isspace() or char in {'=', '"', "\\"} for char in text)
    if needs_quotes:
        return f'"{escaped}"'
    return escaped


def build_monitoring_log_event(event: str, **fields: object) -> str:
    parts = [str(event).strip()]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={format_monitoring_log_value(value)}")
    return " ".join(parts)


def create_request_id() -> str:
    return f"req-{uuid4().hex}"


def should_log_request_summary(*, path: str, status_code: int, duration_ms: int) -> bool:
    if path in EXCLUDED_REQUEST_SUMMARY_PATHS:
        return False
    if status_code >= 500 or duration_ms >= SLOW_REQUEST_THRESHOLD_MS:
        return True
    return any(path.startswith(prefix) for prefix in IMPORTANT_REQUEST_PATH_PREFIXES)


def log_request_summary(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
) -> None:
    if should_log_request_summary(
        path=path,
        status_code=status_code,
        duration_ms=duration_ms,
    ):
        logger.info(
            build_monitoring_log_event(
                "API_REQUEST_SUMMARY",
                request_id=request_id,
                method=method,
                path=path,
                status=status_code,
                duration_ms=duration_ms,
            )
        )


def ensure_request_id_header(message: Message, request_id: str) -> Message:
    header_name = REQUEST_ID_HEADER.lower().encode("latin-1")
    headers = [
        (name, value)
        for name, value in message.get("headers", [])
        if name.lower() != header_name
    ]
    headers.append((header_name, request_id.encode("latin-1")))
    updated_message = dict(message)
    updated_message["headers"] = headers
    return updated_message


class RequestMonitoringMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._get_request_id(scope)
        self._set_request_state(scope, request_id)
        started_at = time.perf_counter()
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                message = ensure_request_id_header(message, request_id)
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                log_request_summary(
                    request_id=request_id,
                    method=str(scope["method"]),
                    path=str(scope["path"]),
                    status_code=int(message["status"]),
                    duration_ms=duration_ms,
                )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.exception(
                build_monitoring_log_event(
                    "API_REQUEST_EXCEPTION",
                    request_id=request_id,
                    method=scope["method"],
                    path=scope["path"],
                    duration_ms=duration_ms,
                    response_started=response_started,
                )
            )
            raise

    @staticmethod
    def _get_request_id(scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name.lower() == REQUEST_ID_HEADER.lower().encode("latin-1"):
                request_id = value.decode("latin-1").strip()
                if request_id:
                    return request_id
                break
        return create_request_id()

    @staticmethod
    def _set_request_state(scope: Scope, request_id: str) -> None:
        state = scope.get("state")
        if state is None:
            state = {}
            scope["state"] = state
        state["request_id"] = request_id


def install_request_monitoring(app: ASGIApp) -> ASGIApp:
    return RequestMonitoringMiddleware(app)
