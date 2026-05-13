from __future__ import annotations

from typing import Any

import httpx


class RetrievalClientError(RuntimeError):
    """Base retrieval proxy error."""


class RetrievalClientUnavailableError(RetrievalClientError):
    """Raised when the retrieval API cannot be reached."""


class RetrievalClientResponseError(RetrievalClientError):
    """Raised when the retrieval API returns an application error."""

    def __init__(self, *, status_code: int, detail: Any):
        super().__init__(f"retrieval-api returned HTTP {status_code}")
        self.status_code = status_code
        self.detail = detail


class RetrievalClient:
    def __init__(
        self,
        *,
        base_url: str | None,
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.transport = transport

    async def search_jobs(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url:
            raise RetrievalClientUnavailableError("retrieval_api_url is not configured")

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_s,
                transport=self.transport,
            ) as client:
                response = await client.post("/api/v1/internal/jobs/search", json=payload)
        except httpx.RequestError as exc:
            raise RetrievalClientUnavailableError(
                f"retrieval-api request failed: {exc.__class__.__name__}"
            ) from exc

        if response.is_error:
            detail: Any
            try:
                detail = response.json()
            except ValueError:
                detail = {
                    "code": "retrieval_api_error",
                    "message": response.text,
                }
            raise RetrievalClientResponseError(status_code=response.status_code, detail=detail)

        return response.json()

    async def export_jobs_csv(self, payload: dict[str, Any]) -> bytes:
        if not self.base_url:
            raise RetrievalClientUnavailableError("retrieval_api_url is not configured")

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_s,
                transport=self.transport,
            ) as client:
                response = await client.post("/api/v1/internal/jobs/search/export", json=payload)
        except httpx.RequestError as exc:
            raise RetrievalClientUnavailableError(
                f"retrieval-api request failed: {exc.__class__.__name__}"
            ) from exc

        if response.is_error:
            detail: Any
            try:
                detail = response.json()
            except ValueError:
                detail = {
                    "code": "retrieval_api_error",
                    "message": response.text,
                }
            raise RetrievalClientResponseError(status_code=response.status_code, detail=detail)

        return response.content
