from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import source_category_registry as registry_module


def test_fetch_ctgoodjobs_registry_html_uses_async_category_page_helper(monkeypatch):
    seen = {}

    async def fake_fetch_category_page_html(url: str, *, client=None, timeout_s: float = 30.0):
        seen["url"] = url
        seen["timeout_s"] = timeout_s
        return "<html>registry</html>"

    monkeypatch.setattr(registry_module, "fetch_category_page_html", fake_fetch_category_page_html)

    html = registry_module._fetch_ctgoodjobs_registry_html()

    assert html == "<html>registry</html>"
    assert seen == {
        "url": "https://jobs.ctgoodjobs.hk/jobs",
        "timeout_s": 30.0,
    }


def test_source_category_registry_returns_stale_cache_when_refresh_fails(monkeypatch):
    registry = registry_module.SourceCategoryRegistry(ctgoodjobs_ttl_s=0.0)
    payload = [
        {
            "id": "ctgoodjobs:021",
            "name": "Information Technology",
            "slug": "information-technology",
            "source_site": "ctgoodjobs",
        }
    ]

    calls = {"count": 0}

    def fake_fetch() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            return """
            <html><body><script>
            self.__next_f.push([1,"1b:[[\\\"$\\\",\\\"$L35\\\",null,{}],[\\\"$\\\",\\\"$L38\\\",null,{\\\"filter\\\":{\\\"JobFunction\\\":[]},\\\"jobcats\\\":[{\\\"total\\\":34,\\\"id\\\":\\\"021_jc\\\",\\\"name\\\":\\\"Information Technology\\\",\\\"nameForUrl\\\":\\\"information-technology\\\"}],\\\"jobFunctions\\\":[]}]]"]);
            </script></body></html>
            """
        raise RuntimeError("upstream down")

    monkeypatch.setattr(registry_module, "_fetch_ctgoodjobs_registry_html", fake_fetch)

    first = registry.list_categories(source_site="ctgoodjobs")
    second = registry.list_categories(source_site="ctgoodjobs")

    assert first == payload
    assert second == payload
    assert calls["count"] == 2


def test_source_category_registry_returns_static_fallback_on_first_fetch_failure(monkeypatch):
    registry = registry_module.SourceCategoryRegistry(ctgoodjobs_ttl_s=0.0)

    monkeypatch.setattr(
        registry_module,
        "_fetch_ctgoodjobs_registry_html",
        lambda: (_ for _ in ()).throw(RuntimeError("upstream down")),
    )

    categories = registry.list_categories(source_site="ctgoodjobs")

    ids = {category["id"] for category in categories}
    assert "ctgoodjobs:021" in ids
    assert any(category["slug"] == "information-technology" for category in categories)
