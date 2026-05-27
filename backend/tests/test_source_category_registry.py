from __future__ import annotations

from types import SimpleNamespace

from app.services import source_category_registry


def test_jobsdb_categories_are_cached_between_calls(monkeypatch):
    calls = []

    def fake_get_all_categories():
        calls.append(True)
        return [
            SimpleNamespace(id=1200, name="Engineering", slug="engineering"),
            SimpleNamespace(id=1300, name="Marketing", slug="marketing"),
        ]

    monkeypatch.setattr(source_category_registry, "get_all_categories", fake_get_all_categories)

    registry = source_category_registry.SourceCategoryRegistry()

    first = registry.list_categories(source_site="jobsdb")
    second = registry.list_categories(source_site="jobsdb")

    assert first == second
    assert calls == [True]
