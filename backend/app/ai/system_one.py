from __future__ import annotations

from dataclasses import dataclass, field
import time
from collections.abc import Callable
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from pydantic import ValidationError


class ChoiceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["choice"] = "choice"
    instructions: JsonValue | None = None
    criteria: dict[str, JsonValue | None]


class NoulQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["noul"] = "noul"
    instructions: JsonValue | None = None
    criteria: dict[Literal["true", "false"], JsonValue] | None = None


class ScoreQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["score"] = "score"
    instructions: JsonValue | None = None
    criteria: list[JsonValue] = Field(min_length=1)


SystemOneQuestion = Annotated[
    ChoiceQuestion | NoulQuestion | ScoreQuestion,
    Field(discriminator="type"),
]


class SystemOneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: JsonValue
    model: str = Field(min_length=1)
    questions: dict[str, SystemOneQuestion] = Field(min_length=1)


class ChoiceAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["choice"]
    choice: str
    confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, Annotated[float, Field(ge=0, le=1)]]


class NoulAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["noul"]
    noul: float = Field(ge=0, le=1)


class ScoreAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["score"]
    score: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    legend: dict[int, JsonValue]
    probabilities: dict[int, Annotated[float, Field(ge=0, le=1)]]


SystemOneAnswer = Annotated[
    ChoiceAnswer | NoulAnswer | ScoreAnswer,
    Field(discriminator="type"),
]


class SystemOneUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost: float | None = Field(default=None, ge=0)


class _SystemOneResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    model: str
    provider: str | None = None
    answers: dict[str, SystemOneAnswer]
    usage: SystemOneUsage


@dataclass(frozen=True)
class SystemOneResult:
    status: Literal["answered", "abstained", "unavailable", "invalid"]
    request_id: str | None = None
    model: str | None = None
    provider: str | None = None
    answers: dict[str, SystemOneAnswer] = field(default_factory=dict)
    usage: SystemOneUsage | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class NativeSystemOneClient:
    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        http_client: httpx.AsyncClient,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._http_client = http_client
        self._clock = clock

    async def aclose(self) -> None:
        await self._http_client.aclose()

    async def evaluate(self, request: SystemOneRequest) -> SystemOneResult:
        started_at = self._clock()
        try:
            response = await self._http_client.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=request.model_dump(exclude_none=True),
            )
        except httpx.RequestError:
            return SystemOneResult(
                status="unavailable",
                latency_ms=self._latency_ms(started_at),
                error_code="transport_error",
                error_message="System One request could not be completed",
            )
        if not response.is_success:
            return SystemOneResult(
                status="unavailable",
                latency_ms=self._latency_ms(started_at),
                error_code=f"http_{response.status_code}",
                error_message=f"System One returned HTTP {response.status_code}",
            )
        try:
            response_data = response.json()
        except ValueError:
            return SystemOneResult(
                status="invalid",
                latency_ms=self._latency_ms(started_at),
                error_code="invalid_json",
                error_message="System One returned a non-JSON response",
            )
        try:
            payload = _SystemOneResponse.model_validate(response_data)
        except ValidationError:
            return SystemOneResult(
                status="invalid",
                latency_ms=self._latency_ms(started_at),
                error_code="invalid_response",
                error_message="System One returned an invalid response",
            )
        if set(payload.answers) != set(request.questions) or any(
            payload.answers[name].type != question.type
            for name, question in request.questions.items()
        ):
            return SystemOneResult(
                status="invalid",
                latency_ms=self._latency_ms(started_at),
                error_code="answer_mismatch",
                error_message="System One answers did not match the requested questions",
            )
        return SystemOneResult(
            status="answered",
            request_id=payload.id,
            model=payload.model,
            provider=payload.provider,
            answers=payload.answers,
            usage=payload.usage,
            latency_ms=self._latency_ms(started_at),
        )

    def _latency_ms(self, started_at: float) -> int:
        return max(0, int((self._clock() - started_at) * 1000))
