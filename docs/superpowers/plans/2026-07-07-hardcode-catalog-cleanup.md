# Hardcode Catalog Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the highest-value duplicated hardcode by making scheduler source metadata and AI provider metadata flow from backend-owned catalogs, while leaving second-pass historical defaults such as `schedule.location = "Hong Kong"` untouched for now.

**Architecture:** Introduce two backend-owned catalogs: one for crawl sources and one for AI providers. The frontend will stop maintaining its own copies of source/provider lists, crawl mode options, and default page-depth rules, and will instead render from API payloads backed by those catalogs. Database-backed job filters stay as-is because they are already dynamic; this plan only targets duplicated product metadata and cross-layer default drift.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy, React 19, Vitest, Testing Library, pytest

---

## File Map

### Backend

- Create: `backend/app/services/source_catalog.py`
  - Single source of truth for supported crawl sources, labels, category id types, supported crawl modes, and default max pages.
- Create: `backend/app/services/ai_provider_catalog.py`
  - Single source of truth for frontend-facing AI provider metadata such as labels, descriptions, editable fields, secret request keys, and custom API format options.
- Create: `backend/tests/services/test_source_catalog.py`
  - Verifies source catalog contents and source-aware default page depth resolution.
- Create: `backend/tests/services/test_runtime_capabilities_service.py`
  - Verifies runtime capabilities expose source catalog data needed by the scheduler UI.
- Create: `backend/tests/services/test_ai_provider_catalog.py`
  - Verifies provider catalog metadata shape and ordering.
- Create: `backend/tests/api/test_settings_response.py`
  - Verifies the settings response helper includes the provider catalog.
- Modify: `backend/app/services/runtime_capabilities_service.py`
  - Replace handwritten per-source metadata with catalog-backed serialization.
- Modify: `backend/app/api/crawl_jobs.py`
  - Stop maintaining a local supported-source set; validate against the shared catalog helper.
- Modify: `backend/app/api/schedules.py`
  - Stop maintaining a local supported-source set; validate against the shared catalog helper.
- Modify: `backend/app/repositories/schedule_repository.py`
  - Stop maintaining a repository-local supported-source set; normalize against the shared helper.
- Modify: `backend/app/services/scheduler_service.py`
  - Stop maintaining a service-local supported-source set; normalize against the shared helper.
- Modify: `backend/app/schemas/crawl_job.py`
  - Make manual crawl `max_pages` optional so the backend can resolve defaults by source instead of relying on a mismatched schema default.
- Modify: `backend/app/services/crawl_job_dispatch_service.py`
  - Resolve source-aware `max_pages` defaults through the shared source catalog helper.
- Modify: `backend/app/api/settings.py`
  - Include the provider catalog in the AI settings response payload.

### Frontend

- Modify: `frontend/src/components/scraper/crawlMode.js`
  - Convert helper functions from hardcoded source metadata to payload-driven helpers.
- Modify: `frontend/src/components/scraper/maxPages.js`
  - Convert default max pages helper from hardcoded source metadata to payload-driven helper.
- Modify: `frontend/src/components/scraper/ScheduleForm.jsx`
  - Read crawl mode options and default page depth from scheduler source metadata passed down from the runtime capabilities response.
- Modify: `frontend/src/components/scraper/ScheduleManager.jsx`
  - Replace hardcoded source options and local source defaults with backend-backed source metadata.
- Modify: `frontend/src/components/scraper/crawlMode.test.js`
  - Verify crawl mode helpers are driven by supplied source metadata rather than file-local constants.
- Modify: `frontend/src/components/scraper/maxPages.test.js`
  - Verify page-depth resolution is driven by supplied source metadata.
- Modify: `frontend/src/components/scraper/ScheduleManager.test.jsx`
  - Verify source labels and defaults come from the capabilities payload.
- Modify: `frontend/src/components/settings/AISettingsPage.jsx`
  - Replace local provider catalogs with API-driven provider metadata.
- Modify: `frontend/src/components/settings/AISettingsPage.test.jsx`
  - Verify provider cards, editable fields, and custom API format options are rendered from the payload-provided provider catalog.

### Explicitly Out of Scope For This Plan

- `backend/app/models/schedule.py` historical `location = "Hong Kong"` default
- `frontend/src/components/charts/CategoryChart.jsx` color constants
- `frontend/src/components/charts/SkillChart.jsx` display bucket ordering
- `frontend/src/App.jsx` route/view constants
- `frontend/src/components/scraper/ScheduleForm.jsx` and `ScheduleList.jsx` cron presets

These remain second-pass cleanup items because they are not the highest-value duplicated cross-layer metadata.

---

### Task 1: Add a Backend Source Catalog and Remove the Manual Crawl Default Drift

**Files:**
- Create: `backend/app/services/source_catalog.py`
- Create: `backend/tests/services/test_source_catalog.py`
- Modify: `backend/app/schemas/crawl_job.py`
- Modify: `backend/app/services/crawl_job_dispatch_service.py`

- [ ] **Step 1: Write the failing backend source catalog tests**

```python
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.source_catalog import (
    build_source_catalog,
    list_supported_source_sites,
    resolve_default_max_pages,
)


def test_source_catalog_exposes_supported_sources_and_defaults():
    catalog = build_source_catalog()

    assert list_supported_source_sites() == ("jobsdb", "ctgoodjobs", "offertoday")
    assert catalog["jobsdb"]["label"] == "JobsDB"
    assert catalog["jobsdb"]["default_crawl_mode"] == "headed"
    assert catalog["jobsdb"]["default_max_pages"] == 3
    assert catalog["ctgoodjobs"]["supported_crawl_modes"] == ["headed"]
    assert catalog["offertoday"]["default_max_pages"] == 50


def test_resolve_default_max_pages_is_source_aware():
    assert resolve_default_max_pages("jobsdb") == 3
    assert resolve_default_max_pages("ctgoodjobs") == 3
    assert resolve_default_max_pages("offertoday") == 50


def test_manual_dispatch_uses_source_default_max_pages_when_max_pages_is_missing():
    payload = CrawlJobDispatchService().build_manual_request_payload(
        source_site="offertoday",
        crawl_phase="listing",
        crawl_mode=None,
        category_ids=[],
        keywords=None,
        max_pages=None,
    )

    assert payload["max_pages"] == 50
```

- [ ] **Step 2: Run the new backend tests and confirm they fail for the expected reason**

Run: `python -m pytest -q backend/tests/services/test_source_catalog.py`

Expected:
- `ModuleNotFoundError: No module named 'app.services.source_catalog'`
- or `TypeError` because `build_manual_request_payload()` still requires `max_pages: int`

- [ ] **Step 3: Implement the shared source catalog and the source-aware max-pages fallback**

```python
# backend/app/services/source_catalog.py
from __future__ import annotations

from typing import Any

from app.crawl_modes import get_supported_crawl_modes, resolve_crawl_mode

SOURCE_LABELS = {
    "jobsdb": "JobsDB",
    "ctgoodjobs": "CTgoodjobs",
    "offertoday": "OfferToday",
}

SOURCE_CATEGORY_ID_TYPES = {
    "jobsdb": "integer",
    "ctgoodjobs": "string",
    "offertoday": "integer",
}

SOURCE_DEFAULT_MAX_PAGES = {
    "jobsdb": 3,
    "ctgoodjobs": 3,
    "offertoday": 50,
}


def list_supported_source_sites() -> tuple[str, ...]:
    return tuple(SOURCE_LABELS.keys())


def is_supported_source_site(source_site: str | None) -> bool:
    return str(source_site or "").strip().lower() in SOURCE_LABELS


def resolve_default_max_pages(source_site: str | None) -> int:
    normalized = str(source_site or "").strip().lower()
    return SOURCE_DEFAULT_MAX_PAGES.get(normalized, 3)


def build_source_catalog() -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for source_site in list_supported_source_sites():
        payload[source_site] = {
            "key": source_site,
            "label": SOURCE_LABELS[source_site],
            "category_id_type": SOURCE_CATEGORY_ID_TYPES[source_site],
            "supported_crawl_modes": list(get_supported_crawl_modes(source_site)),
            "default_crawl_mode": resolve_crawl_mode(source_site, None),
            "default_max_pages": resolve_default_max_pages(source_site),
        }
    return payload
```

```python
# backend/app/schemas/crawl_job.py
class CrawlJobCreateRequest(BaseModel):
    ...
    max_pages: int | None = Field(default=None, ge=1, le=1000)
```

```python
# backend/app/services/crawl_job_dispatch_service.py
from app.services.source_catalog import resolve_default_max_pages


def build_manual_request_payload(..., max_pages: int | None, ...):
    ...
    return {
        ...
        "max_pages": int(max_pages) if max_pages is not None else resolve_default_max_pages(source_site),
        ...
    }
```

- [ ] **Step 4: Re-run the backend source catalog tests and confirm they pass**

Run: `python -m pytest -q backend/tests/services/test_source_catalog.py`

Expected:
- `3 passed`

- [ ] **Step 5: Commit the source catalog foundation**

```bash
git add backend/app/services/source_catalog.py backend/app/schemas/crawl_job.py backend/app/services/crawl_job_dispatch_service.py backend/tests/services/test_source_catalog.py
git commit -m "fix: centralize crawl source defaults"
```

---

### Task 2: Feed the Shared Source Catalog Into Runtime Capabilities and Source Validation

**Files:**
- Create: `backend/tests/services/test_runtime_capabilities_service.py`
- Modify: `backend/app/services/runtime_capabilities_service.py`
- Modify: `backend/app/api/crawl_jobs.py`
- Modify: `backend/app/api/schedules.py`
- Modify: `backend/app/repositories/schedule_repository.py`
- Modify: `backend/app/services/scheduler_service.py`

- [ ] **Step 1: Write the failing runtime capabilities and validation tests**

```python
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

    payload = build_runtime_capabilities()

    assert payload["sources"]["jobsdb"]["label"] == "JobsDB"
    assert payload["sources"]["jobsdb"]["default_max_pages"] == 3
    assert payload["sources"]["ctgoodjobs"]["supported_crawl_modes"] == ["headed"]
    assert payload["sources"]["offertoday"]["default_max_pages"] == 50
```

- [ ] **Step 2: Run the runtime capabilities test and confirm it fails**

Run: `python -m pytest -q backend/tests/services/test_runtime_capabilities_service.py`

Expected:
- `KeyError: 'label'`
- or missing `default_max_pages` / `supported_crawl_modes` assertions

- [ ] **Step 3: Replace duplicated source sets and handwritten source payloads with the shared helper**

```python
# backend/app/services/runtime_capabilities_service.py
from app.services.source_catalog import build_source_catalog


def _source_capabilities() -> dict[str, dict[str, Any]]:
    catalog = build_source_catalog()
    return {
        source_site: {
            "available": True,
            "listing_supported": True,
            "detail_supported": True,
            "headless_supported": "headless" in entry["supported_crawl_modes"],
            "headed_supported": "headed" in entry["supported_crawl_modes"],
            "manual_action_supported": True,
            "label": entry["label"],
            "category_id_type": entry["category_id_type"],
            "supported_crawl_modes": entry["supported_crawl_modes"],
            "default_crawl_mode": entry["default_crawl_mode"],
            "default_max_pages": entry["default_max_pages"],
        }
        for source_site, entry in catalog.items()
    }
```

```python
# backend/app/api/crawl_jobs.py
from app.services.source_catalog import is_supported_source_site

...
if not is_supported_source_site(effective_source_site):
    raise HTTPException(status_code=400, detail="Unsupported source_site for execution")
```

```python
# backend/app/api/schedules.py
from app.services.source_catalog import is_supported_source_site

...
if not is_supported_source_site(request.source_site):
    raise HTTPException(status_code=400, detail="Unsupported source_site for execution")
```

```python
# backend/app/repositories/schedule_repository.py
from app.services.source_catalog import is_supported_source_site

...
if not is_supported_source_site(source_site):
    normalized["is_active"] = False
```

```python
# backend/app/services/scheduler_service.py
from app.services.source_catalog import is_supported_source_site

...
if not is_supported_source_site(source_site):
    logger.info("Skipping scheduler registration for unsupported source_site '%s' ...", source_site)
    return False
```

- [ ] **Step 4: Re-run the runtime capabilities test and confirm it passes**

Run: `python -m pytest -q backend/tests/services/test_runtime_capabilities_service.py`

Expected:
- `1 passed`

- [ ] **Step 5: Commit the shared source validation wiring**

```bash
git add backend/app/services/runtime_capabilities_service.py backend/app/api/crawl_jobs.py backend/app/api/schedules.py backend/app/repositories/schedule_repository.py backend/app/services/scheduler_service.py backend/tests/services/test_runtime_capabilities_service.py
git commit -m "fix: share crawl source metadata across services"
```

---

### Task 3: Make the Scheduler UI Consume Backend Source Metadata

**Files:**
- Modify: `frontend/src/components/scraper/crawlMode.js`
- Modify: `frontend/src/components/scraper/maxPages.js`
- Modify: `frontend/src/components/scraper/ScheduleForm.jsx`
- Modify: `frontend/src/components/scraper/ScheduleManager.jsx`
- Modify: `frontend/src/components/scraper/crawlMode.test.js`
- Modify: `frontend/src/components/scraper/maxPages.test.js`
- Modify: `frontend/src/components/scraper/ScheduleManager.test.jsx`

- [ ] **Step 1: Write the failing frontend helper tests for payload-driven source metadata**

```javascript
import { describe, expect, it } from 'vitest';

import { getCrawlModeOptionsForSource, resolveDefaultCrawlMode } from './crawlMode';
import { resolveDefaultMaxPages } from './maxPages';

const SOURCE_CATALOG = {
  jobsdb: {
    supported_crawl_modes: ['headless', 'headed'],
    default_crawl_mode: 'headed',
    default_max_pages: 3,
  },
  ctgoodjobs: {
    supported_crawl_modes: ['headed'],
    default_crawl_mode: 'headed',
    default_max_pages: 3,
  },
  offertoday: {
    supported_crawl_modes: ['headless', 'headed'],
    default_crawl_mode: 'headless',
    default_max_pages: 50,
  },
};

describe('scheduler source helpers', () => {
  it('reads crawl mode options from supplied source metadata', () => {
    expect(getCrawlModeOptionsForSource('ctgoodjobs', SOURCE_CATALOG)).toEqual([
      { value: 'headed', label: 'Headed' },
    ]);
  });

  it('reads default crawl mode and page depth from supplied source metadata', () => {
    expect(resolveDefaultCrawlMode('offertoday', SOURCE_CATALOG)).toBe('headless');
    expect(resolveDefaultMaxPages('offertoday', SOURCE_CATALOG)).toBe(50);
  });
});
```

- [ ] **Step 2: Write the failing scheduler UI test that proves source labels come from capabilities**

```javascript
it('renders source labels from the runtime capabilities payload', async () => {
  globalThis.fetch = createFetchMock({
    capabilities: {
      scheduler: { available: true, manual_run_available: true, owner: 'scheduler-worker', worker_name: 'scheduler-worker', heartbeat_status: 'fresh', reason: null },
      sources: {
        jobsdb: { label: 'JobsDB Live', supported_crawl_modes: ['headless', 'headed'], default_crawl_mode: 'headed', default_max_pages: 3, category_id_type: 'integer' },
        ctgoodjobs: { label: 'CTGoodJobs Live', supported_crawl_modes: ['headed'], default_crawl_mode: 'headed', default_max_pages: 3, category_id_type: 'string' },
        offertoday: { label: 'OfferToday Live', supported_crawl_modes: ['headless', 'headed'], default_crawl_mode: 'headless', default_max_pages: 50, category_id_type: 'integer' },
      },
    },
  });

  render(<ScheduleManager onNavigateToAI={vi.fn()} />);

  expect(await screen.findByRole('option', { name: 'CTGoodJobs Live' })).toBeInTheDocument();
  expect(screen.getByRole('option', { name: 'OfferToday Live' })).toBeInTheDocument();
});
```

- [ ] **Step 3: Run the scheduler helper and UI tests to verify they fail**

Run: `npm test -- --run src/components/scraper/crawlMode.test.js src/components/scraper/maxPages.test.js src/components/scraper/ScheduleManager.test.jsx`

Expected:
- helper tests fail because the functions do not accept source metadata yet
- UI test fails because `SOURCE_OPTIONS` still comes from a local constant

- [ ] **Step 4: Refactor the scheduler helpers and components to accept backend metadata**

```javascript
// frontend/src/components/scraper/crawlMode.js
const FALLBACK_CRAWL_MODE_OPTIONS = [
  { value: 'headless', label: 'Headless' },
  { value: 'headed', label: 'Headed' },
];

export function resolveDefaultCrawlMode(sourceSite, sources = {}) {
  return sources?.[sourceSite]?.default_crawl_mode || 'headless';
}

export function getCrawlModeOptionsForSource(sourceSite, sources = {}) {
  const supportedModes = sources?.[sourceSite]?.supported_crawl_modes;
  if (!Array.isArray(supportedModes) || supportedModes.length === 0) {
    return FALLBACK_CRAWL_MODE_OPTIONS;
  }

  return supportedModes.map((mode) => ({
    value: mode,
    label: mode === 'headed' ? 'Headed' : 'Headless',
  }));
}
```

```javascript
// frontend/src/components/scraper/maxPages.js
export function resolveDefaultMaxPages(sourceSite, sources = {}) {
  return Number(sources?.[sourceSite]?.default_max_pages ?? 3);
}
```

```javascript
// frontend/src/components/scraper/ScheduleManager.jsx
const sourceCatalog = capabilities?.sources || {};
const sourceOptions = Object.entries(sourceCatalog).map(([value, entry]) => ({
  value,
  label: entry.label || value,
}));

const immediateCrawlModeOptions = getCrawlModeOptionsForSource(currentSourceSite, sourceCatalog);
```

```javascript
// frontend/src/components/scraper/ScheduleForm.jsx
function ScheduleForm({ ..., sourceCatalog = {}, ... }) {
  ...
  const crawlModeOptions = getCrawlModeOptionsForSource(sourceSite, sourceCatalog);
  ...
  maxPages: resolveDefaultMaxPages(sourceSite, sourceCatalog),
}
```

- [ ] **Step 5: Re-run the scheduler tests and confirm they pass**

Run: `npm test -- --run src/components/scraper/crawlMode.test.js src/components/scraper/maxPages.test.js src/components/scraper/ScheduleManager.test.jsx`

Expected:
- all targeted scheduler tests pass

- [ ] **Step 6: Commit the scheduler catalog refactor**

```bash
git add frontend/src/components/scraper/crawlMode.js frontend/src/components/scraper/maxPages.js frontend/src/components/scraper/ScheduleForm.jsx frontend/src/components/scraper/ScheduleManager.jsx frontend/src/components/scraper/crawlMode.test.js frontend/src/components/scraper/maxPages.test.js frontend/src/components/scraper/ScheduleManager.test.jsx
git commit -m "fix: drive scheduler sources from runtime capabilities"
```

---

### Task 4: Add a Backend-Owned AI Provider Catalog

**Files:**
- Create: `backend/app/services/ai_provider_catalog.py`
- Create: `backend/tests/services/test_ai_provider_catalog.py`
- Create: `backend/tests/api/test_settings_response.py`
- Modify: `backend/app/api/settings.py`

- [ ] **Step 1: Write the failing provider catalog tests**

```python
from app.api.settings import _build_ai_settings_response
from app.services.ai_provider_catalog import build_ai_provider_catalog


def test_provider_catalog_exposes_frontend_provider_metadata():
    payload = build_ai_provider_catalog()

    assert [provider["key"] for provider in payload["providers"]] == [
        "anthropic",
        "gemini",
        "custom",
        "zhipu",
        "mock",
    ]

    custom = payload["providers_by_key"]["custom"]
    assert custom["label"] == "Custom"
    assert custom["secret_request_key"] == "custom_api_key"
    assert [field["request_key"] for field in custom["fields"]] == [
        "custom_model",
        "custom_base_url",
        "custom_api_format",
    ]
    assert payload["custom_api_format_options"] == [
        {"value": "anthropic", "label": "Anthropic"},
        {"value": "openai_responses", "label": "OpenAI Responses"},
    ]


def test_ai_settings_response_includes_provider_catalog():
    class FakeService:
        def serialize_persisted_config(self):
            return {}

        def serialize_effective_config(self):
            return {}

    payload = _build_ai_settings_response(FakeService())

    assert "provider_catalog" in payload
    assert payload["provider_catalog"]["providers"][0]["key"] == "anthropic"
```

- [ ] **Step 2: Run the provider catalog tests and confirm they fail**

Run: `python -m pytest -q backend/tests/services/test_ai_provider_catalog.py backend/tests/api/test_settings_response.py`

Expected:
- `ModuleNotFoundError: No module named 'app.services.ai_provider_catalog'`
- or missing `provider_catalog` in the settings response

- [ ] **Step 3: Implement the backend AI provider catalog and expose it from the settings response**

```python
# backend/app/services/ai_provider_catalog.py
from __future__ import annotations


def build_ai_provider_catalog() -> dict:
    providers = [
        {
            "key": "anthropic",
            "label": "Anthropic",
            "description": "Claude-compatible runtime",
            "fields": [
                {"key": "model", "label": "Model", "request_key": "anthropic_model"},
                {"key": "base_url", "label": "Base URL", "request_key": "anthropic_base_url"},
            ],
            "secret_request_key": "anthropic_api_key",
        },
        {
            "key": "gemini",
            "label": "Gemini",
            "description": "Fast general-purpose model",
            "fields": [
                {"key": "model", "label": "Model", "request_key": "gemini_model"},
            ],
            "secret_request_key": "gemini_api_key",
        },
        {
            "key": "custom",
            "label": "Custom",
            "description": "Custom OpenAI or Anthropic endpoint",
            "fields": [
                {"key": "model", "label": "Model", "request_key": "custom_model"},
                {"key": "base_url", "label": "Base URL", "request_key": "custom_base_url"},
                {"key": "api_format", "label": "API Format", "request_key": "custom_api_format"},
            ],
            "secret_request_key": "custom_api_key",
        },
        {
            "key": "zhipu",
            "label": "Zhipu",
            "description": "Credential-only setup",
            "fields": [],
            "secret_request_key": "zhipu_api_key",
        },
        {
            "key": "mock",
            "label": "Mock",
            "description": "Built-in fallback for testing",
            "fields": [],
            "secret_request_key": None,
        },
    ]

    return {
        "providers": providers,
        "providers_by_key": {provider["key"]: provider for provider in providers},
        "custom_api_format_options": [
            {"value": "anthropic", "label": "Anthropic"},
            {"value": "openai_responses", "label": "OpenAI Responses"},
        ],
    }
```

```python
# backend/app/api/settings.py
from app.services.ai_provider_catalog import build_ai_provider_catalog


def _build_ai_settings_response(service: AIRuntimeSettingsService) -> dict:
    ...
    return {
        "persisted_config": service.serialize_persisted_config(),
        "effective_config": service.serialize_effective_config(),
        "runtime_status": job_status,
        "company_runtime_status": company_status,
        "provider_catalog": build_ai_provider_catalog(),
    }
```

- [ ] **Step 4: Re-run the provider catalog tests and confirm they pass**

Run: `python -m pytest -q backend/tests/services/test_ai_provider_catalog.py backend/tests/api/test_settings_response.py`

Expected:
- `2 passed`

- [ ] **Step 5: Commit the provider catalog response contract**

```bash
git add backend/app/services/ai_provider_catalog.py backend/app/api/settings.py backend/tests/services/test_ai_provider_catalog.py backend/tests/api/test_settings_response.py
git commit -m "fix: expose ai provider catalog from settings api"
```

---

### Task 5: Make the AI Settings UI Render From the Provider Catalog Payload

**Files:**
- Modify: `frontend/src/components/settings/AISettingsPage.jsx`
- Modify: `frontend/src/components/settings/AISettingsPage.test.jsx`

- [ ] **Step 1: Write the failing AI settings UI test for payload-driven provider labels**

```javascript
it('renders provider cards and custom api format options from provider_catalog', async () => {
  const payload = clonePayload(aiSettingsPayload);
  payload.provider_catalog = {
    providers: [
      {
        key: 'anthropic',
        label: 'Anthropic Live',
        description: 'Claude-compatible runtime',
        fields: [
          { key: 'model', label: 'Model', request_key: 'anthropic_model' },
          { key: 'base_url', label: 'Base URL', request_key: 'anthropic_base_url' },
        ],
        secret_request_key: 'anthropic_api_key',
      },
      {
        key: 'custom',
        label: 'Custom Live',
        description: 'Custom endpoint runtime',
        fields: [
          { key: 'model', label: 'Model', request_key: 'custom_model' },
          { key: 'base_url', label: 'Base URL', request_key: 'custom_base_url' },
          { key: 'api_format', label: 'API Format', request_key: 'custom_api_format' },
        ],
        secret_request_key: 'custom_api_key',
      },
      {
        key: 'mock',
        label: 'Mock Live',
        description: 'Built-in fallback',
        fields: [],
        secret_request_key: null,
      },
    ],
    providers_by_key: {},
    custom_api_format_options: [
      { value: 'anthropic', label: 'Anthropic' },
      { value: 'openai_responses', label: 'OpenAI Responses' },
    ],
  };

  globalThis.fetch = vi.fn((url) => {
    if (url === '/api/v1/settings/ai') {
      return mockJsonResponse(payload);
    }
    throw new Error(`Unhandled fetch: ${url}`);
  });

  render(<AISettingsPage />);

  expect(await screen.findByRole('button', { name: /^Anthropic Live\b/i })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /^Custom Live\b/i })).toBeInTheDocument();
  expect(screen.getByRole('option', { name: 'OpenAI Responses' })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the AI settings UI test and confirm it fails**

Run: `npm test -- --run src/components/settings/AISettingsPage.test.jsx`

Expected:
- provider labels still come from local `PROVIDER_OPTIONS` / `PROVIDER_LABELS`
- custom API format options still come from local `CUSTOM_API_FORMAT_OPTIONS`

- [ ] **Step 3: Refactor AI settings to read provider metadata from the response payload**

```javascript
// frontend/src/components/settings/AISettingsPage.jsx
function getProviderCatalog(payload) {
  return payload?.provider_catalog || {
    providers: [],
    providers_by_key: {},
    custom_api_format_options: [],
  };
}

function getProviderOptions(payload) {
  return getProviderCatalog(payload).providers || [];
}

function getProviderByKey(payload, providerKey) {
  const catalog = getProviderCatalog(payload);
  return catalog.providers_by_key?.[providerKey]
    || catalog.providers?.find((provider) => provider.key === providerKey)
    || null;
}

function toProviderLabel(payload, provider) {
  return getProviderByKey(payload, provider)?.label || String(provider || 'Unknown');
}
```

```javascript
// frontend/src/components/settings/AISettingsPage.jsx
const providerOptions = getProviderOptions(settingsPayload);
const providerMeta = getProviderByKey(settingsPayload, selectedProvider);
const providerFields = providerMeta?.fields || [];
const providerDescription = providerMeta?.description || '';
const secretRequestKey = providerMeta?.secret_request_key || null;
const customApiFormatOptions = getProviderCatalog(settingsPayload).custom_api_format_options || [];
```

```javascript
// frontend/src/components/settings/AISettingsPage.jsx
{providerOptions.map((provider) => {
  const isSelected = provider.key === selectedProvider;
  return (
    <button
      key={provider.key}
      ...
      onClick={() => updateProfileProvider(profileKey, provider.key)}
    >
      <strong>{provider.label}</strong>
      <span>{getProviderSetupLabel(providerMeta)}</span>
      <small>{provider.description}</small>
    </button>
  );
})}
```

- [ ] **Step 4: Re-run the AI settings UI test and confirm it passes**

Run: `npm test -- --run src/components/settings/AISettingsPage.test.jsx`

Expected:
- targeted AI settings test passes with payload-provided labels and API format options

- [ ] **Step 5: Commit the AI settings catalog refactor**

```bash
git add frontend/src/components/settings/AISettingsPage.jsx frontend/src/components/settings/AISettingsPage.test.jsx
git commit -m "fix: drive ai settings providers from api catalog"
```

---

### Task 6: Run Focused Verification Across Backend and Frontend

**Files:**
- Test: `backend/tests/services/test_source_catalog.py`
- Test: `backend/tests/services/test_runtime_capabilities_service.py`
- Test: `backend/tests/services/test_ai_provider_catalog.py`
- Test: `backend/tests/api/test_settings_response.py`
- Test: `frontend/src/components/scraper/crawlMode.test.js`
- Test: `frontend/src/components/scraper/maxPages.test.js`
- Test: `frontend/src/components/scraper/ScheduleManager.test.jsx`
- Test: `frontend/src/components/settings/AISettingsPage.test.jsx`

- [ ] **Step 1: Run the focused backend verification suite**

Run: `python -m pytest -q backend/tests/services/test_source_catalog.py backend/tests/services/test_runtime_capabilities_service.py backend/tests/services/test_ai_provider_catalog.py backend/tests/api/test_settings_response.py`

Expected:
- all focused backend catalog tests pass

- [ ] **Step 2: Run the focused frontend verification suite**

Run: `npm test -- --run src/components/scraper/crawlMode.test.js src/components/scraper/maxPages.test.js src/components/scraper/ScheduleManager.test.jsx src/components/settings/AISettingsPage.test.jsx`

Expected:
- all focused frontend scheduler and AI settings tests pass

- [ ] **Step 3: Run one final combined verification pass after rebasing any local conflicts**

Run: `git status --short`

Expected:
- only intentional plan-scope files are modified
- unrelated user changes remain untouched

- [ ] **Step 4: Commit the final verification checkpoint**

```bash
git add backend/tests frontend/src/components/scraper frontend/src/components/settings
git commit -m "test: cover source and provider catalogs"
```

---

## Self-Review

- Spec coverage:
  - Scheduler source options, crawl modes, and default page depth are covered by Tasks 1-3.
  - AI provider list, editable field definitions, and custom API format options are covered by Tasks 4-5.
  - Historical backend-only defaults such as `schedule.location = "Hong Kong"` are explicitly deferred out of scope.
- Placeholder scan:
  - No `TODO`, `TBD`, or “similar to previous task” shortcuts remain.
- Type consistency:
  - `max_pages` becomes `int | None` only in the manual crawl request path and is resolved through `resolve_default_max_pages(source_site)`.
  - Provider catalog keys are consistently named `key`, `label`, `description`, `fields`, and `secret_request_key` across backend and frontend tasks.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-07-hardcode-catalog-cleanup.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
