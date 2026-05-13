from __future__ import annotations

from typing import Any

import httpx


class RecommendationClientError(RuntimeError):
    """Base recommendation proxy error."""


class RecommendationClientUnavailableError(RecommendationClientError):
    """Raised when the recommendation API cannot be reached."""


class RecommendationClientResponseError(RecommendationClientError):
    """Raised when the recommendation API returns an application error."""

    def __init__(self, *, status_code: int, detail: Any):
        super().__init__(f"recommendation-api returned HTTP {status_code}")
        self.status_code = status_code
        self.detail = detail


class RecommendationClient:
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

    async def get_job_recommendations(self, job_id, *, limit: int = 5) -> dict[str, Any]:
        if not self.base_url:
            raise RecommendationClientUnavailableError("recommendation_api_url is not configured")

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_s,
                transport=self.transport,
            ) as client:
                response = await client.get(
                    "/api/v1/internal/recommendations/jobs",
                    params={"job_id": str(job_id), "limit": limit},
                )
        except httpx.RequestError as exc:
            raise RecommendationClientUnavailableError(
                f"recommendation-api request failed: {exc.__class__.__name__}"
            ) from exc

        if response.is_error:
            detail: Any
            try:
                detail = response.json()
            except ValueError:
                detail = {
                    "code": "recommendation_api_error",
                    "message": response.text,
                }
            raise RecommendationClientResponseError(status_code=response.status_code, detail=detail)

        return response.json()
