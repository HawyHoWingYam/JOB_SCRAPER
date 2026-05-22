# Operator Perspective: User-facing Job Search

## Current Responsibilities

This perspective covers searching jobs, applying filters, refining result scopes, exporting results, and viewing job details plus related jobs.

## Current Implementation Map

- Frontend: `frontend/src/components/JobBrowser.jsx`, `FilterPanel.jsx`, `SearchBar.jsx`, `JobDetailModal.jsx`
- Backend: `backend/app/api/jobs.py`, `filters.py`, `recommendations.py`
- Search schemas: `backend/app/schemas/job_search.py`

## Data and Control Flow

Users build a search scope in the browser. The frontend posts scope layers and retrieval mode to `/api/v1/jobs/search`. Export sends the active scope to `/api/v1/jobs/search/export`. Job details fetch related jobs through recommendation proxy support.

## Tests and Coverage

- `frontend/src/components/JobBrowser.test.jsx`
- `frontend/src/components/JobDetailModal.test.jsx`
- `backend/tests/test_retrieval_client.py`
- `backend/tests/test_retrieval_api.py`
- `backend/tests/test_recommendations_api.py`
- `backend/tests/test_internal_recommendations_api.py`
- `backend/tests/test_job_recommendation_service.py`

## Known Gaps or Risks

- Semantic/hybrid features fail if ML side services are unavailable.
- No route-level deep link exists for a search state.
- Export behavior intentionally ignores pending draft edits, which must remain clear to users.
- Related jobs and semantic search depend on sidecar readiness that is not advertised to users before interaction.

## Optimization Backlog

- Add capability-aware controls for lexical, semantic, hybrid, related jobs, and export modes so unavailable sidecars do not appear as generic errors.
- Encode search scope, filters, retrieval mode, and selected job in URL state once React Router is introduced.
- Include export metadata for active filters, retrieval mode, fallback state, result count, and generation timestamp.
- Standardize error copy and retry behavior for sidecar 503s across search and job detail recommendations.

## Follow-up Audit Questions

- Should search state be encoded in URL/query params?
- Should unavailable semantic mode be hidden or disabled?
- Should exports include metadata describing active filters and retrieval mode?
