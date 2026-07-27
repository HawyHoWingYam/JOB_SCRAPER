# Implementation Plan

1. Add focused registry tests that build a CTgoodjobs catalog with multiple
   invalid paths, establish the red aggregate-error signal, and prove an
   existing registry is byte-for-byte unchanged after the failed sync.
2. Define the minimal adapter compile protocol and aggregate domain error shape,
   preserving existing `CatalogValidationError` compatibility.
3. Update `synchronize_catalog(...)` and its startup callers so the owning
   adapter validates all required discovered nodes before observation
   projection or ORM mutation.
4. Make aggregate diagnostics deterministic, bounded, and rich enough to name
   Source, classification ID, native ID, label, invalid field/value, and stable
   reason/code without leaking arbitrary metadata.
5. Add source-isolation coverage: invalid CTgoodjobs fails while valid JobsDB
   and OfferToday catalogs still synchronize.
6. Run the tight regression loop:
   `cd backend && pytest -q tests/test_source_classification_registry.py tests/test_source_classification_adapters.py`.
7. Run affected integration checks:
   `cd backend && pytest -q tests/test_crawl_scope_service.py tests/test_crawl_control_api.py`.
8. Run backend formatting/lint/type checks required by the repository, then
   `git diff --check`; inspect the final diff for accidental changes to existing
   user work.

## Risk and Rollback Points

- Do not change `synchronize(...)` semantics for incremental path observation.
- Do not place network smoke checks in the pre-write gate; `compile` must remain
  deterministic and local.
- If aggregate error changes break callers, keep the legacy scalar fields and
  add structured details additively.
- Reverting the registry gate and aggregate error changes restores prior sync
  behavior without a database rollback because this task introduces no schema
  changes.
