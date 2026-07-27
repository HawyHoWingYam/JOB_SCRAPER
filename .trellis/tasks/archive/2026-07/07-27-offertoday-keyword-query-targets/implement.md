# Implementation plan

1. Add deterministic OfferToday sweep constants and target-contract fixtures.
   Extend the OfferToday target decoder to read both legacy empty/browse and new
   keyword/search snapshots while keeping new compilation keyword-only.
2. Change only the OfferToday Source Classification adapter to compile 36
   ordered hybrid Query Targets for each queryable top-level node. Add compiler,
   fingerprint, ordering, category-attribution, and no-empty-keyword tests.
3. Add source-aware scope validation: exactly one OfferToday classification,
   OfferToday Page Depth default 100 with no product maximum, Run Page Cap
   default 3600, checked integer multiplication, and `cap >= 36 * depth`.
   Cover zero/multiple/inactive/child/non-queryable selections. Preserve existing
   JobsDB/CTgoodjobs cardinality, limits, and the generic 5000-page ceiling.
4. Make workload review's system ceiling source-aware: OfferToday relies on its
   reviewed operator cap; all other sources retain the 5000 cap. Cover one-off,
   Run-now, Automation review, prepared-plan, and scheduled-dispatch paths with
   the same validation owner.
5. Update Automation readiness so under-budget saved OfferToday Automations are
   retained but cannot dispatch until explicitly reviewed and saved. Do not
   migrate or silently expand persisted limits.
6. Add a narrow OfferToday non-job-card classifier at the response-row boundary,
   filter confirmed advertisement/banner cards before identity validation, and
   project additive `non_job_cards_observed` page/task metrics without changing
   frozen historical research serializers. Test mixed ad + invalid-job precedence.
7. Ensure OfferToday standalone and Scrapy runtimes consume the 36 frozen
   `search/list` targets with condition-local cursors, `rcd_type=None`, existing
   retain-and-continue Page Depth behavior, existing fail-fast hard stops, and
   aggregate Run Page Cap enforcement. Lock cross-condition identity dedupe and
   single detail targeting.
8. Update the existing Task Control wizard with OfferToday-only single-select,
   `100 / 3600` defaults, editable inputs, immediate `36 × depth` calculation,
   semantic invalid-state messaging, and server-review reconciliation. Do not
   duplicate the keyword list or compile targets in React.
9. Add explicit JobsDB/CTgoodjobs regression snapshots for adapter compilation,
   scope cardinality, Page Depth limits/defaults, 5000-page system cap, wizard
   behavior, resolved scope JSON, and request payloads. Production code for those
   source adapters and runtimes is outside the allowed change set.
10. Run focused backend tests for source adapters, target contracts, scope/workload
    review, Automation dispatch, listing runner, standalone/Scrapy execution,
    metrics, and historical serialization. Run focused Task Control Vitest,
    scoped ESLint, backend Ruff/compile checks, frontend production build, and
    `git diff --check`.
11. Run the bounded no-write OfferToday live comparison as an opt-in report, not
    a deterministic CI gate. Verify all 36 conditions are accepted,
    advertisement cards are ignored and counted, report novelty against the
    historical category-only baseline, and confirm no logical page claim exceeds
    the reviewed operator cap.

## Risk and rollback points

- Target decoder compatibility must land before new target compilation; do not
  proceed if historical task projection or frozen-target execution tests fail.
- Source-aware validation must be shared by review and dispatch; stop if the UI
  and server can produce different workload validity.
- Non-job filtering must use positive advertisement evidence; stop if a fixture
  can classify a job-shaped missing-identity row as ignorable.
- After keyword plans are persisted, rollback may disable creation but must keep
  their decoder/runtime support.

## Validation commands

Exact focused test paths should be confirmed against the touched files before
implementation. The expected gates are:

```text
backend adapter/contract/scope/automation/listing focused pytest
backend Ruff and compile checks for touched modules
frontend Task Control focused Vitest and ESLint
frontend production build
git diff --check
bounded no-write OfferToday live probe
```
