import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.services.company_enrichment_service as company_enrichment_service_module


class FakeQuery:
    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def all(self):
        return []


class FakeDB:
    def query(self, *_args, **_kwargs):
        return FakeQuery()


class RecordingLLM:
    def __init__(self, *, web_search_supported):
        self.web_search_supported = web_search_supported
        self.calls = []

    async def generate(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        return "Generated company description"

    def supports_web_search(self):
        return self.web_search_supported


@pytest.mark.asyncio
async def test_company_enrichment_service_skips_web_search_for_unsupported_clients(monkeypatch):
    llm = RecordingLLM(web_search_supported=False)
    monkeypatch.setattr(company_enrichment_service_module, "get_llm_client", lambda scope="jobs": llm)

    service = company_enrichment_service_module.CompanyEnrichmentService()
    company = SimpleNamespace(
        id="company-1",
        name="Acme Health",
        industry="Healthcare",
        location="Hong Kong",
        ai_description=None,
    )

    result = await service._generate_company_description(company, FakeDB())

    assert result == "Generated company description"
    assert llm.calls[0]["kwargs"]["web_search"] is False
    assert "Search the web first" not in llm.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_company_enrichment_service_requests_web_search_for_supported_clients(monkeypatch):
    llm = RecordingLLM(web_search_supported=True)
    monkeypatch.setattr(company_enrichment_service_module, "get_llm_client", lambda scope="jobs": llm)

    service = company_enrichment_service_module.CompanyEnrichmentService()
    company = SimpleNamespace(
        id="company-1",
        name="Acme Health",
        industry="Healthcare",
        location="Hong Kong",
        ai_description=None,
    )

    await service._generate_company_description(company, FakeDB())

    assert llm.calls[0]["kwargs"]["web_search"] is True
    assert "Search the web first" in llm.calls[0]["prompt"]
