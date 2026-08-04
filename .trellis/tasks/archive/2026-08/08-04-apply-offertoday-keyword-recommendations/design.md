# Design

## Boundaries

- `OfferTodayKeywordCatalog` and its CSV preview/confirm API remain the sole mutation boundary for the live catalog.
- `offertoday_keyword_entries` remains the runtime authority for crawl-control keyword targets.

## Data flow

1. Export the live catalog, make seven additions and one `enabled=false` change, then preview it.
2. Confirm only when the preview action set exactly matches the approved delta.
3. Re-export/query the catalog to verify enabled count, retained disabled row, and audit record.

## Compatibility and safety

- `Dynamics 365` and `penetration testing` supplement rather than replace their broader forms.
- `pentest` is disabled in the live catalog rather than deleted, preserving evidence and audit history.
- The enabled total remains below the catalog limit of 150.
- Database mutation is rollback-capable by a later governed CSV change that re-enables `pentest` and disables the seven additions.
- No crawl dispatch follows confirmation.

## Operational decision

The live mutation must stop before confirmation if the catalog baseline differs from the reviewed 127-term snapshot or if preview reports any unapproved action. Default-pack code is deliberately untouched because its catalog implementation is untracked WIP owned by another active task.
