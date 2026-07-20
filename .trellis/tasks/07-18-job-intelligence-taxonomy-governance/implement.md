# Job intelligence taxonomy and governance implementation plan

## Execution strategy

The parent is a coordination and integration task. Do not start it as a monolithic implementation target. Start and finish children in their explicit dependency order, then use the parent for final cross-child acceptance and release coordination.

Inline mode applies: each child loads `trellis-before-dev` before editing and does not curate `implement.jsonl`/`check.jsonl`.

## Child order

1. `07-18-job-intelligence-foundation`
2. After child 1 contracts are reviewed, children 2–5 may proceed independently:
   - `07-18-source-job-attributes`
   - `07-18-canonical-job-taxonomy-governance`
   - `07-18-company-industry-governance`
   - `07-18-skill-governance`
3. `07-18-job-intelligence-product-surfaces` after child 2–5 API contracts stabilize.
4. `07-18-job-intelligence-cutover-rebuild` after child 2–5 schemas and rebuild commands pass dry-run fixtures. It may be prepared in parallel with child 6 but may not execute against the live corpus early.
5. Parent integration review after children 6 and 7 pass.

## Parent coordination checklist

- [x] Confirm every child PRD states its real dependencies and excludes tree-position assumptions.
- [x] Confirm every child design uses the parent Module seams and ubiquitous language.
- [x] Confirm common `RevisionRef`, `Provenance`, `DecisionCommand`, audit, idempotency, and conflict contracts are stable before children 2–5 start.
- [x] Confirm Source Catalog integration is an Adapter and not a new crawl authority in this task.
- [x] Confirm domain children own their migrations, rebuild commands, Interface tests, and compatibility adapters.
- [x] Confirm product surfaces consume real backend schemas and cannot execute decisions outside governance routes.
- [x] Confirm cutover uses dry-run, backup identity, writer quiescence, checkpoints, reconciliation, and rollback.
- [x] Perform a final terminology search for retired labels: `Job Type`, `AI Category`, bare canonical `Classification`, and `Provisional Skills`.
- [x] Perform a final legacy-field search and classify every remaining use as archived evidence, compatibility adapter, or defect.

Detailed evidence and the compatibility/live-operation dispositions are recorded
in `research/parent-integration-acceptance.md`.

## Integration validation commands

Run from the repository root unless noted:

```bash
cd backend && ruff check app tests scripts && black --check app tests scripts && mypy app
cd backend && pytest -q
cd frontend && npm run lint
cd frontend && npm test
cd frontend && npm run build
python3 ./.trellis/scripts/task.py validate 07-18-job-intelligence-taxonomy-governance
```

Before final acceptance, run package-specific checks from `.trellis/spec/backend/index.md` and `.trellis/spec/frontend/index.md` after loading their Quality Check sections through `trellis-check`.

## Cross-child integration scenarios

1. [x] A JobsDB Job with multiple source classifications and `Full time + Permanent` retains all raw evidence, produces two Employment Types, and never invents Primary classification.
2. [x] An OfferToday Job with multiple `jobFunctions` preserves every path; one valid constrained AI Job Subcategory assignment records full provenance.
3. [x] An invalid/fallback canonical decision leaves the Job Unassigned and appears in Job Taxonomy Review; operator resolution is idempotent/audited and triggers embedding invalidation.
4. [x] A company source label matching an approved HSIC mapping creates a most-specific Company Industry Assignment; ancestor filter includes it.
5. [x] An unmapped company label and AI recommendation create a Company Industry Review Item; no assignment occurs before local-operator decision.
6. [x] A technical unknown creates a Skill Candidate and Unreviewed Skill Mentions; operator merge rewrites all affected mentions and creates governed Job-Skill links atomically.
7. [x] Job Browser, Job Detail, Companies, Dashboard, and governance queues serialize and render the same contract and language.
8. [x] Disposable cutover dry-run/execute rehearsals preserve the documented 17,596-Job corpus identities/raw evidence, archive legacy values, rebuild projections, reindex embeddings, and pass reconciliation before simulated writer reopening. Live execution remains separately approved.

## Release and rollback gates

- Do not run destructive cutover while any child 2–5 validation is incomplete.
- Record application image/commit, schema revision, taxonomy content hashes, database backup ID, and worker state before execution.
- Fail closed if writers cannot be proven quiesced.
- Keep legacy columns and previous image through the rollback window.
- Reopen writers only after database integrity, projection coverage, unresolved queues, API contracts, frontend smoke flows, and embedding readiness pass.
- If a gate fails, stop at the current checkpoint; either resume idempotently after correction or restore the recorded backup/image.

## Parent completion gate

The parent is planning-ready only when all child artifacts are reviewed. It is implementation-complete only after all children are archived or explicitly accepted, the full integration matrix passes, the final PRD convergence pass is complete, and no required follow-up remains hidden in a child.
