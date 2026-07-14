from __future__ import annotations

from app.api import progress as progress_api


def test_collect_progress_payload_delegates_to_shared_service(monkeypatch):
    captured = {}
    sentinel_repository = object()

    def fake_collect_progress_payload(*, repository=None):
        captured["repository"] = repository
        return {
            "active": {},
            "all": {},
            "backlog": {},
            "has_active": False,
            "has_backlog": False,
        }

    monkeypatch.setattr(
        progress_api,
        "collect_progress_payload",
        fake_collect_progress_payload,
        raising=False,
    )
    monkeypatch.setattr(progress_api, "repository", sentinel_repository)

    payload = progress_api._collect_progress_payload()

    assert payload == {
        "active": {},
        "all": {},
        "backlog": {},
        "has_active": False,
        "has_backlog": False,
    }
    assert captured == {"repository": sentinel_repository}
