# Implementation plan

- [x] Add failing registry/scope cross-source contract tests.
- [x] Add ordinary schema/module and adapter synchronization.
- [x] Migrate Source path projection and preflight off revision references.
- [x] Simplify crawl authoring, dispatch, API, and frontend scope.
- [x] Remove Source Catalog and provenance-repair vertical slices.
  Governance UI/API/service/repository/validation/admin/repair/runtime seams,
  ORM models, revision-pinned mapping coverage fields, and all six database
  tables are deleted. Canonical mapping coverage now reads the ordinary current
  classification registry and permits unmapped current classifications.
- [x] Run the final focused Source/AI/crawl tests, frontend tests/build, and
  architecture search for legacy symbols.

The user explicitly authorized the sandbox-only destructive cutover without a
backup. Alembic head `20260726_180000` is applied; all six governance tables are
absent while collected Jobs, Companies, classification paths, dispatch plans,
and enrichment-owned data remain in place.
