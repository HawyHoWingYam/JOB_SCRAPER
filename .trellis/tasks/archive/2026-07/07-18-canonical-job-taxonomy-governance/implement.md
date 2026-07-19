# Canonical job taxonomy governance implementation plan

## Dependencies

- Reuse the archived Foundation revision/provenance/decision/audit/idempotency/
  outbox contracts. Automated evaluation must not use the human decision UoW.
- Consume the archived Source Job Attributes read/evidence Interface. The
  Canonical Module, not Source Catalog or Source Attributes, owns mapping and
  allowed-slice authority.
- Preserve old taxonomy rows and `jobs.subcategory_id` as comparison evidence;
  do not execute live seed activation, migration, backfill, or cutover.

## Ordered checklist

1. Load `trellis-before-dev`; read backend database/error/logging/AI/search
   specs, Foundation/Source Attribute specs, ADR-0007/0014, and applicable
   frontend type-safety guidance.
2. Add failing explicit-code seed and mapping-release validator tests: exact
   initial 25/63/198 counts, complete removal/rejection of exact `General` and
   `Unknown` fallback nodes, duplicate/orphan/code drift, assignability, pinned
   Source Catalog revision/fingerprint/identity-set coverage, mutually
   exclusive disposition cardinality, stable target references, and
   deterministic reports/hashes. Report the 15-ID CTgoodjobs legacy-constant
   discrepancy without treating the constant as coverage authority.
3. Convert the taxonomy/mapping fixtures to committed stable-code manifests,
   omitting all 25 `General → General` paths and replacing legacy default paths
   with explicit reviewed dispositions. Bootstrap code generation is a
   one-time authoring tool; runtime publication rejects missing codes and never
   derives identity from labels.
4. Add additive Alembic/ORM tables for replacement revision-bound nodes, active
   pointers, mapping releases/Source Catalog coverages/targets, assignments,
   and review items. Add same-revision composite FKs, `RESTRICT`/`CASCADE`,
   immutability triggers, partial active uniqueness, constrained statuses/
   reasons/methods, and indexes.
5. Implement validation, Foundation revision identity publication, idempotent
   inactive materialization, count/hash verification, and atomic active-pointer
   switch. Never publish/activate at startup or migration time.
6. Implement Source mapping publication and the complete multi-path truth
   table using Source-qualified evidence IDs and stable canonical target codes:
   exact catalog coverage, blocking missing/excluded/unmapped evidence,
   deterministic convergence/conflict, compatible deterministic-plus-union,
   and allowed-slice-only constrained AI. Never choose by path order.
7. Implement `CanonicalJobTaxonomy.evaluate` one vertical TDD slice at a time:
   reviewed mapping, constrained AI, exact replay, replacement, every review
   reason, assignment removal/supersession, outbox rollback, and two-Session
   concurrency. It flushes but never commits.
8. Integrate `AIEnrichmentService` with typed classifier/model evidence and the
   evaluation seam. Retire production legacy normalizer/create/fallback/
   governance-override authority and add architecture inventory guards.
9. Implement current state/tree reads, opt-in canonical filter/document
    builders, versioned Job Intelligence routes, and backend response fixtures.
    Prove existing live Job API/filter/embedding consumers are not switched;
    broad product UI redesign remains child 6 and coordinated live authority/
    embedding-index cutover remains child 7.
10. Implement review list/read and the two local-operator actions through
    Foundation `GovernanceUnitOfWork`; cover target/version/confirmation/replay/
    audit/outbox atomicity and worker decision-Interface isolation.
11. Implement the deterministic read-only rebuild inspector and JSON/human CLI
    with no apply/execute flag, zero writes, bulk loading, provenance/mapping/
    legacy diagnostics, and pinned revision hashes.
12. Run targeted unit/API/PostgreSQL tests, task-scoped Ruff/Black/mypy,
    Alembic head/offline SQL, disposable-PostgreSQL upgrade/downgrade/re-upgrade
    and raw-constraint rehearsal, then the repository's isolated backend test
    strategy and `trellis-check`.
13. Record executable contracts with `trellis-update-spec`; present the Phase
    3.4 commit plan once, archive the child, and record the session journal.

## Validation

```bash
cd backend && pytest -q \
  tests/test_job_taxonomy_registry.py \
  tests/test_canonical_job_taxonomy_governance.py \
  tests/test_canonical_job_taxonomy_migration.py \
  tests/test_canonical_job_taxonomy_api.py
cd backend && ruff check <changed-python-files>
cd backend && black --check <new-or-reformatted-python-files>
cd backend && mypy --follow-imports=skip <changed-typed-modules>
cd backend && alembic heads
cd frontend && npm test -- --run <exported-contract-consumers>
python3 ./.trellis/scripts/task.py validate 07-18-canonical-job-taxonomy-governance
git diff --check
```

Run real migration/concurrency/constraint tests only against an explicit
disposable PostgreSQL URL. If the documented combined pytest collection
interaction recurs, execute every backend test file in isolation and aggregate
the results. Never point migration/rebuild commands at the live corpus.

## Risk and rollback points

- Do not import old AI-created UUIDs into governed replacement tables or treat
  `jobs.subcategory_id` as an accepted assignment.
- Do not derive stable codes at runtime or silently rebind a code after label/
  parent changes.
- Do not accept current `default_path`, `General`, `fallback_default_path`,
  `create_new`, `governance_override`, or legacy
  `proposed_internal_domain` as assignment authority.
- Do not retain the 25 `General → General` paths in the governed manifest even
  as non-assignable navigation nodes; retain them only in the named legacy
  comparison evidence path until child 7 cutover.
- Do not treat bundled/static Source registries or legacy proposed-domain
  constants as mapping coverage authority; pin immutable published Source
  Catalog revisions and fail closed on catalog drift or absence.
- Do not let multiple Source paths choose by order; conflicting deterministic
  mappings and empty/ambiguous slices enter review.
- Do not expose human decision Interfaces to workers or commit inside automatic
  evaluation/domain transitions.
- A failed release may leave an inactive Foundation revision identity for
  exact retry, but must never leave a partial active tree or mapping pointer.
- Application rollback ignores additive canonical tables; never downgrade or
  delete populated immutable/audit rows and never touch live state in this
  child.
