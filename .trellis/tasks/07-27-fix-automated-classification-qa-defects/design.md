# Design: Fix automated classification QA defects

## Boundary

The parent task coordinates three independently deployable child fixes. It owns the shared requirement set, delivery order, regression gate, and aggregate QA evidence; it has no direct production-code seam.

1. `07-27-invalidate-classification-preview` fixes frontend confirmation authority without changing backend batch semantics.
2. `07-27-localized-generic-skill-retry` fixes governed Skill disposition at ingest and batch processing boundaries.
3. `07-27-company-industry-source-mapping` adds the production mapping dataset/synchronization path and cross-layer readiness contract.

The children do not depend on one another for correctness. This order puts the smallest safety fix first, then the bounded backend curation fix, then the cross-layer mapping delivery.

## Shared contracts

- Classification Processing Batch lifecycle, same-domain exclusion, cross-domain parallelism, Stop, retry lineage, stable Start-time snapshots, item isolation, and transaction rollback remain owned by the shared runtime.
- Preview remains advisory. It must confirm the exact request inputs but does not freeze candidate identities before Start.
- Governed terminal dispositions are not provider failures and must not enter failed-only Retry.
- Current taxonomy and mapping state remain unversioned. No release, revision, review queue, fallback node, or CRUD workspace is introduced.
- Company Industry uses company-level Source Industry Label evidence only. Display-name inference and Job-function inference remain forbidden.

## Compatibility and rollout

- #37 is frontend-only and keeps the existing HTTP request/response contract.
- #36 extends curation JSON compatibly and requires no database schema change.
- #38 reuses `current_source_taxonomy_mappings` for positive mappings. Explicit non-mapping dispositions remain in the governed current-state manifest; no fake target and no schema migration are introduced.
- The #38 management command is the deployment gate. API startup remains read-only with respect to governed mapping data.
- Each child is tested and reviewed independently. Aggregate manual QA runs only after all three children pass their own gates.

## Rollback

- Revert each child independently if its targeted regression gate fails.
- #38 rollback restores the previous current-state manifest and reruns the same idempotent synchronization command. This is file rollback, not a product mapping-version feature.
- Do not close #36, #37, or #38 until manual QA supplies issue-specific evidence; do not close umbrella issues automatically.
