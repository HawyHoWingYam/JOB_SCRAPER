from __future__ import annotations

import json

import httpx
import pytest

from app.ai.system_one import (
    ChoiceQuestion,
    NativeSystemOneClient,
    NoulQuestion,
    ScoreQuestion,
    SystemOneRequest,
)


@pytest.mark.asyncio
async def test_native_system_one_sends_the_full_endpoint_and_returns_usage() -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "jev-latest",
                "answers": {
                    "support": {
                        "type": "choice",
                        "choice": "supported",
                        "confidence": 0.93,
                        "probabilities": {
                            "supported": 0.93,
                            "unsupported": 0.07,
                        },
                    }
                },
                "usage": {"input_tokens": 17, "output_tokens": 3},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        ticks = iter((10.0, 10.125))
        client = NativeSystemOneClient(
            endpoint="https://example.test/v1/systemone",
            api_key="test-secret",
            http_client=http,
            clock=lambda: next(ticks),
        )
        result = await client.evaluate(
            SystemOneRequest(
                state={"text": "Python is required."},
                model="jev-latest",
                questions={
                    "support": ChoiceQuestion(
                        instructions="Does the text support the Skill?",
                        criteria={
                            "supported": "The Skill is a Job requirement.",
                            "unsupported": "The Skill is not a Job requirement.",
                        },
                    )
                },
            )
        )

    assert seen == {
        "url": "https://example.test/v1/systemone",
        "authorization": "Bearer test-secret",
        "body": {
            "state": {"text": "Python is required."},
            "model": "jev-latest",
            "questions": {
                "support": {
                    "type": "choice",
                    "instructions": "Does the text support the Skill?",
                    "criteria": {
                        "supported": "The Skill is a Job requirement.",
                        "unsupported": "The Skill is not a Job requirement.",
                    },
                }
            },
        },
    }
    assert result.status == "answered"
    assert result.model == "jev-latest"
    assert result.answers["support"].choice == "supported"
    assert result.usage.input_tokens == 17
    assert result.usage.output_tokens == 3
    assert result.latency_ms == 125


@pytest.mark.asyncio
async def test_native_system_one_accepts_openrouter_decision_receipt() -> None:
    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "gen-dec-test-receipt",
                "model": "typesafe/jev-1.13-20260917",
                "provider": "TypeSafe",
                "answers": {"is_bug": {"type": "noul", "noul": 0.96}},
                "usage": {
                    "input_tokens": 476,
                    "output_tokens": 70,
                    "cost": 0.000019992,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await NativeSystemOneClient(
            endpoint="https://openrouter.ai/api/alpha/decisions",
            api_key="test-secret",
            http_client=http,
        ).evaluate(
            SystemOneRequest(
                state={"ticket": "Checkout is blank."},
                model="typesafe/jev-1.13",
                questions={"is_bug": NoulQuestion()},
            )
        )

    assert result.status == "answered"
    assert result.request_id == "gen-dec-test-receipt"
    assert result.model == "typesafe/jev-1.13-20260917"
    assert result.provider == "TypeSafe"
    assert result.usage is not None
    assert result.usage.cost == 0.000019992


def test_system_one_answer_probabilities_are_bounded() -> None:
    from pydantic import ValidationError

    from app.ai.system_one import NoulAnswer

    with pytest.raises(ValidationError):
        NoulAnswer(type="noul", noul=1.01)


@pytest.mark.asyncio
async def test_native_system_one_decodes_noul_and_score_answers() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["questions"] == {
            "is_required": {
                "type": "noul",
                "instructions": "Is Python required?",
                "criteria": {"true": "Required", "false": "Not required"},
            },
            "strength": {
                "type": "score",
                "instructions": "How direct is the evidence?",
                "criteria": ["absent", "indirect", "direct"],
            },
        }
        return httpx.Response(
            200,
            json={
                "model": "jev-latest",
                "answers": {
                    "is_required": {"type": "noul", "noul": 0.82},
                    "strength": {
                        "type": "score",
                        "score": 2,
                        "confidence": 0.71,
                        "legend": {"0": "absent", "1": "indirect", "2": "direct"},
                        "probabilities": {"0": 0.05, "1": 0.24, "2": 0.71},
                    },
                },
                "usage": {"input_tokens": 23, "output_tokens": 5},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await NativeSystemOneClient(
            endpoint="https://example.test/v1/systemone",
            api_key="test-secret",
            http_client=http,
        ).evaluate(
            SystemOneRequest(
                state="Python is required.",
                model="jev-latest",
                questions={
                    "is_required": NoulQuestion(
                        instructions="Is Python required?",
                        criteria={"true": "Required", "false": "Not required"},
                    ),
                    "strength": ScoreQuestion(
                        instructions="How direct is the evidence?",
                        criteria=["absent", "indirect", "direct"],
                    ),
                },
            )
        )

    assert result.answers["is_required"].noul == 0.82
    assert result.answers["strength"].score == 2
    assert result.answers["strength"].probabilities[2] == 0.71


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_status", "expected_code"),
    [
        (
            httpx.Response(429, text="secret upstream response"),
            "unavailable",
            "http_429",
        ),
        (httpx.Response(200, text="not-json"), "invalid", "invalid_json"),
        (
            httpx.Response(200, json={"model": "jev-latest", "answers": {}}),
            "invalid",
            "invalid_response",
        ),
    ],
)
async def test_native_system_one_returns_secret_safe_failure_results(
    response: httpx.Response,
    expected_status: str,
    expected_code: str,
) -> None:
    def handle(_: httpx.Request) -> httpx.Response:
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await NativeSystemOneClient(
            endpoint="https://example.test/v1/systemone",
            api_key="do-not-expose-this-key",
            http_client=http,
        ).evaluate(
            SystemOneRequest(
                state="Python is required.",
                model="jev-latest",
                questions={"support": NoulQuestion(instructions="Is Python required?")},
            )
        )

    assert result.status == expected_status
    assert result.error_code == expected_code
    assert "do-not-expose-this-key" not in (result.error_message or "")
    assert "secret upstream response" not in (result.error_message or "")


@pytest.mark.asyncio
async def test_native_system_one_maps_transport_failures_to_unavailable() -> None:
    def disconnect(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("contains-sensitive-network-detail", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(disconnect)) as http:
        result = await NativeSystemOneClient(
            endpoint="https://example.test/v1/systemone",
            api_key="do-not-expose-this-key",
            http_client=http,
        ).evaluate(
            SystemOneRequest(
                state="Python is required.",
                model="jev-latest",
                questions={"support": NoulQuestion()},
            )
        )

    assert result.status == "unavailable"
    assert result.error_code == "transport_error"
    assert result.error_message == "System One request could not be completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answers",
    [
        {},
        {
            "support": {
                "type": "choice",
                "choice": "supported",
                "confidence": 1.0,
                "probabilities": {"supported": 1.0},
            }
        },
    ],
)
async def test_native_system_one_rejects_missing_or_mismatched_answers(
    answers: dict[str, object],
) -> None:
    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "jev-latest",
                "answers": answers,
                "usage": {"input_tokens": 4, "output_tokens": 1},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await NativeSystemOneClient(
            endpoint="https://example.test/v1/systemone",
            api_key="test-secret",
            http_client=http,
        ).evaluate(
            SystemOneRequest(
                state="Python is required.",
                model="jev-latest",
                questions={"support": NoulQuestion()},
            )
        )

    assert result.status == "invalid"
    assert result.error_code == "answer_mismatch"
