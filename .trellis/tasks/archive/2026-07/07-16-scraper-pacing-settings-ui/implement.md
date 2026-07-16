# Implementation plan: Scraper pacing settings UI

1. Extract/introduce a Settings shell while preserving AI Runtime tests and
   behavior.
2. Add pacing API client helpers and normalized frontend value helpers.
3. Build one reusable source card with isolated server/form/action state.
4. Add ranges, units, accessible validation, Save, Reset, and feedback.
5. Add active detail-task count, apply-to-new-tasks warning, and Crawl Tasks
   navigation.
6. Add read-only pacing summary/link to Direct Override without changing its
   crawl payload.
7. Add focused Settings/Direct Override tests, run full frontend tests and build.

## Validation Targets

- `frontend/src/components/settings/AISettingsPage.test.jsx` or its refactored
  Settings-shell equivalents
- `frontend/src/components/scraper/ScheduleManager.test.jsx`
- frontend lint/test/build commands defined by the package

## Rollback

The new Settings section and Direct Override summary can be hidden independently;
the backend remains authoritative and no task behavior depends on frontend state.
