# Adapter Boundary: CTgoodjobs Adapter

## Current Responsibilities

The CTgoodjobs adapter handles source-aware category registry parsing, CTgoodjobs category/listing/detail parsing, canonical conversion, headed browser page fetches, and manual-action/resume behavior for CTgoodjobs pages.

## Current Implementation Map

- Source category registry boundary: `backend/app/services/source_category_registry.py`
- CTgoodjobs registry parser/static fallback: `backend/app/scraper/ctgoodjobs/category_registry.py`
- Fetch/list/detail modules: `backend/app/scraper/ctgoodjobs/html_fetcher.py`, `list_scraper.py`, `detail_scraper.py`, `merge.py`
- Browser page scraper: `backend/app/scraper/ctgoodjobs_browser_page_scraper.py`
- Parsers/contracts: `backend/app/sources/ctgoodjobs/parsers.py`, `backend/app/sources/contracts.py`
- Spiders: `backend/crawler/job_crawler/spiders/ctgoodjobs_spider.py`, `ctgoodjobs_headed_spider.py`
- Research-only probe: `backend/app/scraper/ctgoodjobs/research_probe.py`, `backend/scripts/research_ctgoodjobs_probe.py`

## Data and Control Flow

CTgoodjobs source category IDs use `ctgoodjobs:` prefixes. `SourceCategoryRegistry` serves JobsDB categories from the in-repo registry and CTgoodjobs categories from parsed CTgoodjobs registry HTML. The CTgoodjobs registry path has a TTL cache, stale-cache fallback, and static fallback snapshot for first-fetch failures or empty/failed parses.

Headed listing and detail flows use CTgoodjobs browser page scraping. Human-verification detection raises `ManualActionRequiredError` with blocked URL, guidance, and resume context. The headed spider adds listing/detail resume anchors so crawl resume can continue from the blocked category/page or listing target.

`research_probe.py` remains beside production modules but is documented as research-only and should not be required by production imports.

## Tests and Coverage

- `backend/tests/test_ctgoodjobs_spider.py`
- `backend/tests/test_ctgoodjobs_headed_spider.py`
- `backend/tests/test_ctgoodjobs_browser_page_scraper.py`
- `backend/tests/test_ctgoodjobs_html_fetcher.py`
- `backend/tests/test_ctgoodjobs_html_fetch.py`
- `backend/tests/test_ctgoodjobs_category_registry.py`
- `backend/tests/test_ctgoodjobs_parsers.py`
- `backend/tests/test_source_category_registry.py`

## Known Gaps or Risks

- Registry snapshots are in memory/static code only; live parsed category provenance is not persisted with source URL, fetched time, parser version, or fallback reason.
- `research_probe.py` is still physically adjacent to production CTgoodjobs scraper modules, increasing the risk that research orchestration leaks into production paths.
- Manual-action and resume behavior exists for headed flows, but completion is still inferred by operator retry rather than a verified browser challenge completion signal.
- Adapter capability state is not exposed as a first-class status for scheduler or operator UI.
- CTgoodjobs parsing depends on rendered HTML/Next.js payload shapes that can change without API-level notice.

## Optimization Backlog

- Persist CTgoodjobs registry snapshots with source URL, fetched time, parser version, record count, and fallback mode.
- Quarantine the research probe into a clearer research or tooling boundary while keeping reusable parser knowledge in production modules.
- Expose CTgoodjobs adapter capability state for registry availability, headed browser readiness, manual-action requirement, and last successful parse.
- Add verified manual-action completion before resume, with explicit retry accounting for listing and detail phases.
- Add parser and registry drift diagnostics from fixture/live samples to detect HTML shape changes early.

## Follow-up Audit Questions

- Should stale CTgoodjobs registry data be acceptable for scheduled crawls, or only for UI category display?
- Should manual-action resume be source-generic or stay adapter-specific where page semantics differ?
- What retention policy should apply to CTgoodjobs registry snapshots and parse diagnostics?
