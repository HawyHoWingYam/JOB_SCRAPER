# Data Lifecycle: Serving

## Current Responsibilities

Serving exposes persisted and enriched data to the frontend through dashboard, job search, company console, AI console, settings, scheduler, progress, and export endpoints.

## Current Implementation Map

- Main API app: `backend/app/main.py`
- Public routes: `backend/app/api/jobs.py`, `stats.py`, `companies.py`, `ai.py`, `settings.py`, `schedules.py`, `progress.py`
- Frontend shell: `frontend/src/App.jsx`, `frontend/src/components/Sidebar.jsx`
- Frontend views: `Dashboard.jsx`, `JobBrowser.jsx`, `CompaniesPage.jsx`, `AIEnrichmentPage.jsx`, `AISettingsPage.jsx`, `ScheduleManager.jsx`

## Data and Control Flow

The React app uses lazy-loaded views and same-origin API calls in dev through Vite proxy. The main backend serves most public endpoints, while semantic retrieval and recommendation endpoints proxy internally when configured.

## Tests and Coverage

- `frontend/src/App.test.jsx`
- `frontend/src/components/JobBrowser.test.jsx`
- `frontend/src/components/Dashboard.test.jsx`
- `frontend/src/components/companies/CompaniesPage.test.jsx`
- `backend/tests/test_retrieval_client.py`
- `backend/tests/test_recommendations_api.py`

## Known Gaps or Risks

- Runtime feature availability is not fully advertised to the UI.
- Some operator endpoints such as `/health` do not follow the `/api` dev proxy namespace.
- Frontend navigation is state-based rather than route-based, so deep links are not available.
- The main API, retrieval sidecar, and recommendation sidecar expose different readiness surfaces.
- Frontend API helpers still leave some views managing fetch/state/presentation together.

## Optimization Backlog

- Add `/api/v1/capabilities` for semantic search, recommendations, enrichment, headed crawl, scheduler, and operator recovery features.
- Move health and operational status under a consistent `/api/v1/operator` namespace or provide a frontend health adapter that handles `/health` explicitly.
- Introduce React Router deep links for job search, companies, AI runs, schedules, and recovery pages.
- Extract typed frontend API clients/hooks so views stop duplicating fetch, loading, error, and capability handling.

## Follow-up Audit Questions

- Should frontend views migrate to React Router as planned?
- Should API capability metadata drive disabled states for semantic search and operator actions?
- Should health and operator endpoints use a consistent `/api/v1/operator` namespace?
