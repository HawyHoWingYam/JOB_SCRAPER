# Job Intelligence parent integration acceptance

Date: 2026-07-20
Scope: implementation and disposable-environment rehearsal acceptance
Live status: **NO-GO without separate operator approval**

This audit reconciles the seven archived children against the parent contracts.
It does not authorize live publication, activation, migration, corpus mutation,
production smoke, writer shutdown/reopening, or legacy-column cleanup.

## Child convergence

| Child | Integration disposition | Strongest executable evidence |
|---|---|---|
| Foundation | Pass | `backend/tests/test_job_intelligence_foundation.py` covers immutable revisions, atomic decision/audit/idempotency/outbox behavior, concurrency, rollback, and worker isolation. |
| Source Job Attributes | Pass | `backend/tests/test_source_job_attribute_adapters.py`, `backend/tests/test_source_job_attributes.py`, `backend/tests/test_source_job_attribute_ingest.py`, and `backend/tests/test_source_job_attribute_api.py` cover all Sources, Primary rules, seven Employment Types, transactional projection, filtering, APIs, and read-only rebuild evidence. |
| Canonical Job Taxonomy | Pass | `backend/tests/test_canonical_job_taxonomy_governance.py` covers governed release/mapping publication, the multi-path truth table, constrained AI, every review branch, operator decisions, provenance, worker isolation, and deterministic rebuild inspection. |
| Company Industry | Pass | `backend/tests/test_company_industry_governance.py` and `backend/tests/test_company_industry_architecture.py` cover HSIC publication, assignments, subtree filtering, mapping/review decisions, contamination prevention, worker isolation, APIs, and legacy audit. |
| Skill Governance | Pass | `backend/tests/test_skill_governance.py` and `backend/tests/test_skill_governance_architecture.py` cover seed/reference validation, constrained states, Mention/Candidate lifecycle, all four operator actions, governed-only downstream projections, and worker isolation. |
| Product Surfaces | Pass | `backend/tests/test_job_intelligence_response_contracts.py` exports the response contracts consumed by the frontend governance, Job Browser, Job Detail, Company, AI Enrichment, and Dashboard test suites. |
| Cutover/Rebuild | Pass for implementation and disposable rehearsal; live remains NO-GO | `backend/tests/test_job_intelligence_cutover.py` and `backend/tests/integration/test_job_intelligence_rebuild.py` cover safety gates, backup/restore adapters, checkpoint resume, projection rebuilds, embeddings, verification, rollback planning, and the 17,596-Job dry-run scale. |

The Source, Canonical, Company Industry, and Skill PRD acceptance boxes were
historically left unchecked when those tasks were archived. The parent audit
reconciled them to checked only after locating executable evidence for every
criterion. This is documentation convergence, not retroactive live approval.

## Cross-child scenario matrix

| Parent scenario | Evidence | Result |
|---|---|---|
| JobsDB multi-path plus Full-time/Permanent, with no inferred Primary | `test_project_is_idempotent_through_the_source_job_attributes_interface` and the per-Source adapter suites | Pass |
| OfferToday multi-path evidence into constrained AI assignment | `test_offertoday_paths_flow_into_constrained_ai_assignment_with_provenance` | Pass |
| Invalid/fallback canonical output to Unassigned/review, then atomic operator decision | Canonical governance review/decision/replay/outbox tests | Pass |
| Approved Source Industry mapping to most-specific assignment and ancestor match | Company Industry mapping/assignment/subtree tests | Pass |
| Unmapped/AI Company Industry evidence remains review-only until operator action | Company Industry review and worker-isolation tests | Pass |
| Technical unknown to Candidate/Mentions, then atomic governed Skill merge | Skill registration and merge fan-out tests | Pass |
| Backend fixtures and frontend surfaces use one contract and ubiquitous language | Backend fixture-copy assertions and frontend component/API tests | Pass |
| Documented 17,596-Job dry run preserves core identities/raw data without mutation | `test_cutover_dry_run_preserves_the_documented_17596_job_scale` | Pass on explicit disposable PostgreSQL |

## Retired-language classification

The final production search found no active user-facing `Job Type`, `AI
Category`, bare canonical `Classification`, or `Provisional Skill(s)` label.
Remaining occurrences are permitted only in these contexts:

| Occurrence class | Disposition |
|---|---|
| `CONTEXT.md`, ADRs, research, archived task background, and migration audit | Historical policy/evidence; retain. |
| Internal classifier logging or symbols that do not define a product/API label | Internal implementation language; retain unless separately refactored. |
| `provisional_skills` compatibility response/fixture fields | Deprecated contract adapter; product renders `Unreviewed Skill Mentions`; retain through the rollback window. |
| Source-qualified `Source Classification(s)` labels | Current ubiquitous language, not the retired bare canonical label; retain. |

## Legacy-field and endpoint classification

| Path | Classification | Required disposition |
|---|---|---|
| `GET /api/v1/stats/categories` in `backend/app/api/stats.py` | Deprecated canonical legacy aggregation; no active frontend caller. The dashboard uses `/stats/categories/dashboard`. | Retain as a named compatibility endpoint through the rollback window; do not treat it as Crawl Scope or a second governed authority. Deprecate/remove in later cleanup. |
| `jobs.subcategory_id` and legacy taxonomy tables | Archived comparison/cutover evidence. | Preserve through rollback; governed assignment tables remain authoritative. |
| Scalar `Job.employment_type` in response/export code | Deprecated compatibility adapter and legacy evidence. | New filters translate recognised labels into governed codes; no new scalar-equality authority. Remove after consumer migration and rollback window. |
| Scalar Source classification/subclassification fields | Source-evidence compatibility snapshots used by older writers and diagnostic fallbacks. | Preserve and normalize into complete Source Job Attributes; never infer Primary or reconstruct discarded arrays. |
| Legacy Job search `industry` input and raw `industries` filter options | Retired filter authority. | Non-empty scalar input returns 422 directing callers to `company_industry_node_ids`; the compatibility option array is empty. Stable governed node IDs are the only Company Industry filter path. |
| `Company.industry` reads in response/export/enrichment code | Deprecated compatibility/evidence path. | Governed Company Industry assignments are authoritative; retain the scalar only through migration/rollback and never use it as a filter predicate. |
| `CompanyRepository` support for an `industry` input | Compatibility seam, not an active Source Classification write. Current JobsDB, CTgoodjobs, and OfferToday source-aware builders omit `industry` and separately project company-owned evidence. | Retain for legacy/manual adapters, guarded by contamination architecture tests; remove in later cleanup. |
| Legacy fields read by cutover inventory/audit | Immutable archived evidence. | Retain; these reads are intentionally non-authoritative and read-only. |

No remaining active path was found that writes a Job Source Classification into
Company Industry. Manual or Source Industry evidence still enters the Company
Industry Module and creates a governed assignment only under the reviewed
mapping/operator rules.

## Authority boundary

- Crawl Scope continues to consume only published Source Catalog revisions.
  Canonical Job Taxonomy, Company Industry, Employment Type, and Skills remain
  post-collection knowledge and never become crawl authorities.
- Ingest workers receive Source Attribute and Company Industry evidence
  projection Interfaces, not human decision Interfaces.
- Canonical, Skill, and Company Industry decisions are constructed only by the
  trusted-local governance HTTP routes and enforce confirmation, fixed
  `local-operator`, expected version, idempotency, audit, and outbox behavior.
- Product route placement is UX isolation, not authentication. The decision
  routes must not be exposed to an untrusted network.

## Bug analysis: unbounded composite-key rebuild lookup

### 1. Root cause category

- **Primary: E — Implicit assumption.** The rebuild inspector assumed one
  composite `IN` query could safely represent the whole corpus.
- **Secondary: D — Test coverage gap.** The former three-Job test asserted a
  constant two-SELECT shape, which rewarded the unbounded query and never
  exercised PostgreSQL parser capacity.

The exact 17,596-key statement failed with PostgreSQL
`StatementTooComplex: stack depth limit exceeded` before evidence grouping.

### 2. Why earlier checks missed it

1. Small adapter/unit fixtures proved evidence semantics but not statement
   capacity.
2. The no-N+1 assertion treated a single bulk query as universally safe.
3. The documented corpus size existed only as research until the parent added
   a real PostgreSQL scale test.

### 3. Prevention mechanisms

| Priority | Mechanism | Action | Status |
|---|---|---|---|
| P0 | Architecture | Stable-de-duplicate Source keys and cap every composite staging lookup at 100 keys. | Done |
| P0 | Test coverage | Force a two-key batch in the focused test and assert `[4, 4, 2]` SQL parameter counts plus deterministic cross-batch/cross-Source recovery. | Done |
| P0 | Integration | Keep the 17,596-Job disposable-PostgreSQL dry-run test. | Done |
| P1 | Documentation | Record the bounded query contract, failure mode, and wrong/correct implementation in the Source Job Attributes spec. | Done |

### 4. Systematic expansion

- Other cutover domain/embedding rebuild loops already use 100-row batches;
  no second unbounded composite-key query was found in backend application code.
- Future `IN`, `VALUES`, or bulk bind paths must be reviewed against documented
  corpus scale, not only small fixtures or query-count minimization.
- Query-count tests must assert a bounded formula, not demand one statement for
  arbitrarily large inputs.

### 5. Knowledge capture

- [x] Focused red/green regression added.
- [x] Real-scale PostgreSQL regression retained.
- [x] `.trellis/spec/backend/source-job-attributes.md` updated.
- [x] No template-spec mirror exists in this repository, so no template sync is
  applicable.

## Live operator gates

The implementation can be accepted and archived while the following remain
blocked pending a separate operator decision and a fully checked runbook:

1. Pin the actual application image/commit/configuration, schema, governed
   release hashes, database target, and backup identity.
2. Run live inventory and zero-write dry-run, then prove every writer stopped,
   the outbox drained, no active run remains, and the 30-second sentinel is
   stable.
3. Create and restore-test the live backup before any destructive phase.
4. Execute/resume the live rebuild, generate post-embedding runtime smoke
   evidence, and pass cross-layer verification.
5. Obtain a second explicit approval before writer reopening.
6. Keep the prior image, verified backup, and legacy columns through the
   rollback window; cleanup is a later task.

Implementation/rehearsal acceptance therefore does not imply that production
or the live development corpus has been cut over.

## Final verification evidence

Run on 2026-07-20 without connecting a rehearsal command to `jobsdb`:

- Source Attribute batching regression: the pre-fix query emitted one 10-bind
  composite lookup instead of the expected `[4, 4, 2]`; after the fix the
  focused test passed and preserved cross-batch/cross-Source recovery.
- Original 17,596-Job PostgreSQL dry-run: passed in 5.89 seconds and preserved
  core/raw fingerprints with `mutation_detected=false`.
- Backend behavior: all 48 backend test files passed sequentially against the
  explicit `job_intelligence_product_surfaces_test` database; the one existing
  optional pacing PostgreSQL test remained skipped. Combined one-shot
  collection was stopped after reproducing the documented idle collection
  block with no active PostgreSQL query.
- Legacy Company Industry GET compatibility: non-empty `industry` now reaches
  FastAPI as HTTP 422, while `company_industry_node_ids` reaches the governed
  active-revision descendant predicate; both HTTP paths have regression tests.
- Frontend: ESLint and the production build passed. One earlier single-worker
  run passed all 26 files / 172 tests. The final recheck reproduced the
  unrelated `AISettingsPage.test.jsx` loading-state timing flake even with one
  worker: the file alone passed 17/17, and the other 25 files passed in each
  full run. No Job Intelligence task file participates in that loading path.
- Task-scoped Ruff, mypy, and compileall passed. Black check passed for the 11
  changed files already owned by the formatted Job Intelligence surface;
  `app/api/jobs.py` and `app/schemas/job_search.py` remain part of the
  pre-existing repository Black baseline, while the new hunks match Black's
  proposed formatting.
- PostgreSQL test safety: all 12 Job Intelligence suites parse the configured
  URL's database name and prove a fail-closed `_test` guard precedes every
  engine/schema/cleanup operation in each engine-opening function. The meta
  regression also proves raw query text cannot masquerade as a test database
  suffix; eight previously unsafe or incomplete fixtures now use the parsed
  guard.
- Trellis validation and `git diff --check` passed.

The repository-wide Ruff/Black/mypy commands were also executed and remain red
on the pre-existing baseline outside this task (216 Ruff findings, 178 Black
reformat candidates, and 26 mypy errors). No unrelated file was reformatted or
rewritten to hide those results.
