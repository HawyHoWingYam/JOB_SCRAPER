# Implementation plan

## Ordered checklist

1. **Inventory and freeze contracts**
   - Enumerate Company Industry frontend routes/components, backend routes/services/models, migrations, search/facet joins, read-model fields, fixtures, and specs.
   - Enumerate Skill paths that share those modules; write a deletion map before editing.
   - Capture a database backup/restore command and record the destructive sandbox-cutover rollback point.

2. **Initialize Skill taxonomy**
   - Add an explicit manifest synchronization command/service using the existing transform and `CurrentTaxonomyStore.synchronize` seam.
   - Call or enforce the synchronization/readiness contract before Skill enrichment and Candidate review.
   - Add tests for empty, seeded, repeated, and interrupted synchronization.

3. **Reproject existing Skill evidence**
   - Implement bounded, idempotent reprojection of active Skill Mentions after seed synchronization.
   - Verify exact/alias, generic, rejected, unresolved, duplicate-assignment, and rerun behavior.
   - Run the reprojection against a non-production fixture first; production execution is a separate approved operation after code verification.

4. **Replace Skill batch UX with review queue**
   - Add backend list/detail/decision seams for threshold-ready Skill Candidates.
   - Keep selection driven by `skill_auto_create_distinct_job_threshold`; configure current value to 10 through Settings/configuration, not a hardcoded selector constant.
   - Remove preview/start/stop/retry controls from the Skill operator surface.
   - Add explicit operator confirmation for existing match, new leaf Skill under an existing parent, generic, and rejected dispositions.
   - Update Settings label and help text to describe review-list readiness rather than automatic creation.

5. **Update Job Detail and filtering**
   - Keep governed assignments in ordinary Skill display and filters.
   - Move unresolved evidence into a collapsed, clearly pending section; exclude it from canonical filters.
   - Add a distinct taxonomy-unavailable state and regression tests for all empty/enriched combinations.

6. **Delete Company Industry**
   - Remove frontend tabs/pages/filters/detail sections and their API clients.
   - Remove backend routes, schemas, adapters, read-model projections, search/facet joins, and Company Industry-specific batch branches.
   - Remove obsolete fixtures/spec references and prepare the destructive sandbox cutover artifact; do not mutate a non-empty database in place.
   - Confirm shared Skill classification, Job detail Skill payloads, and Job search Skill filters still work.

7. **Full verification and planning closeout**
   - Run backend unit/integration tests for taxonomy, enrichment, Candidate decisions, search, and migrations.
   - Run frontend tests for Settings, Job Detail, Dashboard/Skill review, and removed Company Industry routes.
   - Run type/lint checks and repository-wide searches for stale Company Industry UI/API/database references.
   - Re-read PRD/design/implement, update the ADR status only after approval, then request `task.py start` authorization.

## Validation commands

```bash
cd backend && pytest -q tests/test_current_taxonomies.py tests/test_classification_batch_runtime.py tests/test_stats.py
cd ../frontend && npm test -- --runInBand
cd .. && rg -n "company_industry|Company Industry" backend frontend --glob '!**/node_modules/**'
python3 ./.trellis/scripts/task.py current --source
```

The repository-wide search is expected to return only intentionally retained migration/history or documentation references before those are removed or updated; it must not find live Company Industry routes, UI entry points, search joins, or domain handlers after implementation.

## Risk and rollback points

- Stop before the destructive sandbox cutover if the backup cannot be restored in a disposable database.
- Stop if Skill taxonomy synchronization produces duplicate codes, changes operator-owned nodes, or cannot be rerun safely.
- Stop if removing Company Industry changes shared Skill query paths or breaks Job Detail serialization outside the intended fields.
- Roll back code independently before data migration; after the destructive migration, restore the database backup before reverting code that expects the deleted tables.
