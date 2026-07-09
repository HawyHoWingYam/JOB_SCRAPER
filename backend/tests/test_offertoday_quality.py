from app.sources.offertoday.quality import clean_description_text, normalize_tag_terms
import importlib

import pytest


def test_clean_description_text_removes_boilerplate_lines():
    raw_text = """
    Build ETL pipelines for internal analytics.

    All applications will be treated in strict confidence.
    Personal data collected will be used for recruitment purposes only.
    Apply now.
    """.strip()

    cleaned = clean_description_text(raw_text)

    assert cleaned == "Build ETL pipelines for internal analytics."


def test_normalize_tag_terms_drops_benefit_and_location_noise():
    filtered = normalize_tag_terms(
        [
            "Python",
            "python",
            "Medical Insurance",
            "Annual Leave",
            "Hong Kong",
            "data analysis",
            "stakeholder management and documentation",
        ],
        blocked_terms={"Medical Insurance", "Annual Leave"},
    )

    assert filtered == ["Python", "data analysis"]


@pytest.mark.asyncio
async def test_pause_before_detail_request_uses_offer_specific_jitter(monkeypatch):
    pacing_module = importlib.import_module("app.scraper.offertoday_pacing")
    calls: list[tuple[float, float]] = []

    async def fake_random_delay(min_seconds: float, max_seconds: float) -> None:
        calls.append((min_seconds, max_seconds))

    monkeypatch.setattr(pacing_module, "random_delay", fake_random_delay)

    await pacing_module.pause_before_detail_request()

    assert calls == [(0.75, 2.25)]


@pytest.mark.asyncio
async def test_pause_after_transient_detail_failure_reuses_backoff(monkeypatch):
    pacing_module = importlib.import_module("app.scraper.offertoday_pacing")
    attempts: list[int] = []

    class _FakeBackoff:
        def __init__(self, **kwargs) -> None:
            self.kwargs = dict(kwargs)

        async def wait(self, attempt: int) -> None:
            attempts.append(attempt)

    monkeypatch.setattr(pacing_module, "ExponentialBackoff", _FakeBackoff)

    await pacing_module.pause_after_transient_detail_failure(1)

    assert attempts == [1]
