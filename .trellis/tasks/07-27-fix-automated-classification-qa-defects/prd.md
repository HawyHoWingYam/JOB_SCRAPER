# Fix automated classification QA defects

## Goal

Restore production-safe Automated Classification behavior by fixing the three independently reproducible defects found in QA, while preserving the batch lifecycle, isolation, retry lineage, cancellation, and transaction guarantees that already passed.

## Background

- QA tracking issue: [#34](https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/34), under umbrella [#32](https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/32).
- Full evidence: `.trellis/tasks/07-27-qa-automated-classification-frontend/qa-report.md`.
- Automated regression baseline: 27/27 relevant frontend and backend tests passed during QA.
- The three defects are separately testable and therefore owned by child tasks.

## Requirements

### R1 — Localized generic Skill resolution

Child task: `07-27-localized-generic-skill-retry` · GitHub [#36](https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/36).

Localized generic Skill Mentions such as `項目管理`, `銷售`, and `客戶服務` must resolve to an intentional non-Skill outcome and must not remain eligible for failed-only Retry indefinitely. No partial Skill taxonomy node may be created on failure.

### R2 — Preview invalidation

Child task: `07-27-invalidate-classification-preview` · GitHub [#37](https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/37).

Changing Source or limit after Preview must invalidate the displayed confirmation and disable Start until the operator obtains a fresh Preview for the current inputs. The started Classification Processing Batch must consume the scope the operator actually confirmed.

### R3 — Company Industry Source Mapping setup

Child task: `07-27-company-industry-source-mapping` · GitHub [#38](https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/38).

The product must provide a production-supported way to establish Company Industry Source Mappings from retained Source Industry Labels to governed Company Industries, and must not offer a Company Industry batch that is guaranteed to fail because no usable mapping evidence exists.

For the first production path:

- mappings are installed through a governed import/seed mechanism representing current state, without product-level mapping versions or releases;
- the product exposes mapping coverage/readiness to the operator;
- Start is blocked when the selected Company population has no usable mapped evidence;
- a full operator-facing mapping CRUD editor is deferred.

### R4 — Preserve verified behavior

The fixes must preserve Source/limit filtering, stable candidate snapshots, same-domain mutual exclusion, cross-domain parallelism, cooperative Stop, per-item failure isolation, Retry lineage, reload history, atomic Skill creation, and transaction rollback.

## Acceptance Criteria

- [ ] Each child task has independently testable acceptance criteria tied to its existing GitHub issue.
- [ ] All three child fixes pass their targeted automated tests and the existing 27-test QA regression set.
- [ ] A final integration QA run demonstrates that none of #36, #37, or #38 remains reproducible.
- [ ] Existing lifecycle, concurrency, persistence, atomicity, and rollback behavior remains green.
- [ ] Company Industry Source Mapping import is repeatable and validated, coverage/readiness is visible, and a guaranteed-failure Company batch cannot start.
- [ ] Remaining browser-only coverage limitations are recorded explicitly rather than represented as passed.
- [ ] #36, #37, and #38 receive fix evidence; #32 and #34 receive the aggregate outcome.

## Out of Scope

- Reopening already-passed behavior without evidence of a regression.
- Treating Source Classification display names as canonical identities.
- Inferring a Company Industry from a Job's function when company-level Source Industry Label evidence is absent.
- A full Company Industry Source Mapping CRUD editor in the first fix.
- Product-level Company Industry Source Mapping versions, releases, or revision history.
- Creating duplicate GitHub issues for the three confirmed defects.
