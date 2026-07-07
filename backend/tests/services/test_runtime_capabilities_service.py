from __future__ import annotations

from app.config import settings
from app.services.runtime_capabilities_service import build_runtime_capabilities


def test_runtime_capabilities_expose_backend_source_catalog(monkeypatch):
    monkeypatch.setattr(
        "app.services.runtime_capabilities_service.get_profile_runtime_metadata",
        lambda scope: type(
            "Meta",
            (),
            {
                "is_ready": False,
                "requires_test": False,
                "configured_provider": None,
                "model": None,
                "config_fingerprint": None,
                "last_test_fingerprint": None,
                "degradation_reason": None,
                "last_test_error": None,
                "last_tested_at": None,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.runtime_capabilities_service.get_scheduler_runtime_status",
        lambda: {"enabled": True, "manual_run_available": True},
    )
    monkeypatch.setattr(
        "app.services.runtime_capabilities_service.get_headed_crawl_worker_status",
        lambda: {"available": True},
    )
    monkeypatch.setattr(
        "app.services.runtime_capabilities_service.build_source_catalog",
        lambda: {
            "jobsdb": {
                "key": "jobsdb",
                "label": "Synthetic JobsDB",
                "category_id_type": "integer",
                "supported_crawl_modes": ["headed"],
                "default_crawl_mode": "headed",
                "default_max_pages": 17,
            },
            "ctgoodjobs": {
                "key": "ctgoodjobs",
                "label": "Synthetic CTgoodjobs",
                "category_id_type": "string",
                "supported_crawl_modes": ["headed", "headless"],
                "default_crawl_mode": "headless",
                "default_max_pages": 23,
            },
            "offertoday": {
                "key": "offertoday",
                "label": "Synthetic OfferToday",
                "category_id_type": "integer",
                "supported_crawl_modes": ["headless"],
                "default_crawl_mode": "headless",
                "default_max_pages": 29,
            },
        },
    )

    payload = build_runtime_capabilities()

    assert payload["sources"]["jobsdb"]["label"] == "Synthetic JobsDB"
    assert payload["sources"]["jobsdb"]["default_max_pages"] == 17
    assert payload["sources"]["ctgoodjobs"]["supported_crawl_modes"] == ["headed", "headless"]
    assert payload["sources"]["ctgoodjobs"]["proxy_supported"] is True
    assert payload["sources"]["ctgoodjobs"]["proxy_modes_supported"] == ["headed", "headless"]
    assert payload["sources"]["ctgoodjobs"]["proxy_enabled"] is bool(settings.ctgoodjobs_proxy_enabled)
    assert payload["sources"]["offertoday"]["default_max_pages"] == 29
