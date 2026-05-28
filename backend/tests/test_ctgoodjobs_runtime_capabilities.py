from types import SimpleNamespace

from app.services import runtime_capabilities_service


def test_ctgoodjobs_runtime_capabilities_default_to_headed(monkeypatch):
    monkeypatch.setattr(
        runtime_capabilities_service,
        "get_profile_runtime_metadata",
        lambda scope: SimpleNamespace(
            is_ready=False,
            requires_test=False,
            configured_provider=None,
            model=None,
            active_fingerprint=None,
            config_fingerprint=None,
            last_tested_fingerprint=None,
            last_test_fingerprint=None,
            degradation_reason=None,
            last_test_error=None,
            last_tested_at=None,
            is_degraded=False,
        ),
    )
    monkeypatch.setattr(
        runtime_capabilities_service,
        "get_scheduler_runtime_status",
        lambda: {"enabled": True},
    )

    capabilities = runtime_capabilities_service.build_runtime_capabilities()

    assert capabilities["sources"]["ctgoodjobs"]["default_crawl_mode"] == "headed"
    assert capabilities["sources"]["ctgoodjobs"]["headless_supported"] is False
    assert capabilities["sources"]["ctgoodjobs"]["headed_supported"] is True
    assert capabilities["sources"]["ctgoodjobs"]["proxy_modes_supported"] == ["headed"]
