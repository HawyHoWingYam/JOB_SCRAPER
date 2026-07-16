from types import SimpleNamespace

import pytest

from app.services.detail_pacing import DetailPacingController
from app.services.scraper_pacing_settings_service import ResolvedDetailPacing


class _Token:
    def __init__(self):
        self.checks = 0
        self.sleeps = []

    def raise_if_cancelled(self):
        self.checks += 1

    async def sleep(self, seconds):
        self.sleeps.append(seconds)


@pytest.mark.asyncio
async def test_first_attempt_is_immediate_and_burst_pause_replaces_interval():
    token = _Token()
    persisted = []
    controller = DetailPacingController(
        config=ResolvedDetailPacing(1.0, 3.0, 2, 30.0),
        cancellation_owner=SimpleNamespace(cancellation_token=token),
        persist_attempt_count=persisted.append,
        uniform=lambda minimum, maximum: 2.0,
    )

    await controller.before_attempt()
    await controller.before_attempt()
    await controller.before_attempt()

    assert token.sleeps == [2.0, 30.0]
    assert persisted == [1, 2, 3]


@pytest.mark.asyncio
async def test_resume_uses_cumulative_attempt_position():
    token = _Token()
    persisted = []
    controller = DetailPacingController(
        config=ResolvedDetailPacing(1.0, 3.0, 20, 30.0),
        attempt_count=17,
        cancellation_owner=SimpleNamespace(cancellation_token=token),
        persist_attempt_count=persisted.append,
        uniform=lambda minimum, maximum: 1.5,
    )

    for _ in range(4):
        await controller.before_attempt()

    assert token.sleeps == [1.5, 1.5, 1.5, 30.0]
    assert persisted == [18, 19, 20, 21]


@pytest.mark.asyncio
async def test_zero_burst_pause_does_not_add_sleep():
    token = _Token()
    controller = DetailPacingController(
        config=ResolvedDetailPacing(1.0, 1.0, 1, 0.0),
        attempt_count=1,
        cancellation_owner=SimpleNamespace(cancellation_token=token),
        persist_attempt_count=lambda value: None,
    )

    await controller.before_attempt()

    assert token.sleeps == []
    assert token.checks == 2
