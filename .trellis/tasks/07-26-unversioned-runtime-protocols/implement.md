# Implementation plan

1. Inventory and test the target root API/event/Automation/embedding contracts.
2. Move all backend/frontend/worker callers atomically.
3. Remove revision conflicts/snapshots and implement complete current-row writes.
4. Remove embedding provenance and add full index reset.
5. Build/test current empty-schema bootstrap; remove Alembic.
6. Run backend/frontend/worker integration and forbidden-protocol searches.

Do not deploy a mixed code set at any intermediate commit.

## Progress

- [x] Root API moved from `/api/v1` to `/api`; event-envelope schema version removed.
- [x] Automation revisions, optimistic revision conflicts, ETags, and revision-bound deletes removed; current-row writes are last-wins.
- [x] Board and Crawl Control payload version selectors/fields removed; frontend uses the current projection only.
- [x] Dedicated legacy worker loader and versioned-runtime naming removed.
- [x] Persisted embedding model/version identity and embedding event version metadata removed; freshness now uses document hash and dimensions.
- [x] Move Direct Override and scheduled runs onto current execution authority; reject persisted Crawl Jobs without a Dispatch Plan at worker startup.
- [x] Replace Alembic with an empty-database-only current schema bootstrap and delete migration runtime/history.
- [x] Run final full-scope checks and forbidden-protocol searches.
