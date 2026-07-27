# Technical design

## Boundary

This change is owned entirely by OfferToday source compilation, OfferToday
listing response handling, and source-aware Task Control authoring. The generic
dispatch-plan model may be extended only where it already represents multiple
Query Targets or source-specific limits. JobsDB and CTgoodjobs adapters,
payloads, scope cardinality, defaults, and system-cap behavior are invariants.

## OfferToday Query Target compilation

Define one OfferToday-owned canonical sweep constant in deterministic order:
`A` through `Z`, followed by `0` through `9`. Do not duplicate the list in the
frontend, runner, tests, or dispatch services.

For every queryable OfferToday top-level Source Classification, the adapter
compiles exactly 36 ordered Query Targets. Each target:

- retains the selected classification identity and native category code;
- uses `search_family="classification_keyword_sweep"`;
- uses the production `search/list` endpoint and response-cursor contract;
- carries one non-empty canonical uppercase alphanumeric keyword;
- omits `rcdType` (`rcd_type=None`); and
- has a stable fingerprint derived from its full target payload.

The generic catalog compiler already accepts multiple targets per
classification and hashes their ordered payloads. Remove only OfferToday's
singleton/empty-keyword assertion. Newly compiled targets never contain an
empty keyword or categoryless search.

The public OfferToday target decoder must accept both historical
`browse + empty keyword + rcd_type=7` snapshots and new
`search + alphanumeric keyword + rcd_type=None` snapshots. This compatibility
includes executing a historical frozen browse target through its original
endpoint/parameter contract. It is not permission for new plans to compile
legacy targets.

## Authored scope and workload review

OfferToday listing authoring accepts exactly one active top-level Source
Classification. Enforce cardinality in backend review/plan preparation; the UI
uses a single-select control as guidance, not authority. Other sources keep
their existing selection rules. Zero selections, multiple selections,
inactive/unknown IDs, child nodes, and non-queryable nodes return the existing
structured scope/executability errors before a plan is prepared.

OfferToday defaults are Page Depth `100` and Run Page Cap `3600`. Both remain
editable on the existing execution step. Page Depth is a positive integer with
no OfferToday product-level maximum. The exact estimate is always:

```text
query_target_count = 36
estimated_max_pages = 36 * page_depth
valid when run_page_cap >= estimated_max_pages
```

The frontend shows this calculation and validation immediately as draft input
changes, then replaces it with the authoritative server review. React does not
compile or freeze Query Targets. Backend review and plan preparation repeat the
same source-aware validation.

The generic system listing cap remains `5000` for JobsDB and CTgoodjobs. The
source-aware workload evaluator applies no additional 5000-page ceiling to
OfferToday; its reviewed operator Run Page Cap is the finite hard bound. The
runtime request budget must still reject request `run_page_cap + 1`.

Transport schemas may need a wider technical integer bound than the former
generic Page Depth maximum. Preserve existing source limits through
source-aware validation so widening a shared wire type does not widen JobsDB or
CTgoodjobs behavior. Parse both inputs as safe positive integers, perform
checked multiplication before fingerprinting/persistence, and reject any value
whose `36 * page_depth` or persisted representation would overflow the shared
wire, JavaScript-safe display, database integer, or Run Page Cap contract. These
representational bounds are not presented as an OfferToday product maximum.

## Automation compatibility

Automation review remains read-only and authoritative. Existing OfferToday
Automations are never silently rewritten. If saved limits fail
`run_page_cap >= 36 * page_depth`, review/readiness reports a structured budget
blocker and scheduled dispatch does not launch. The operator edits the existing
Automation, reviews the expanded workload, and explicitly saves valid limits.

There is no database migration. The only historical OfferToday task currently
present is completed. Historical plan/task projections remain readable through
the legacy target decoder.

## Listing runtime

Standalone and Scrapy execution consume only the frozen targets, in their
frozen order. They must not call a helper that regenerates or supplements the
keyword set after confirmation. Cursor state is condition-local and resets
between keywords.

Per-keyword natural exhaustion and `retain-and-continue` Page Depth caps advance
to the next target. WAF/auth/IP blockers, exhausted transport recovery, browser
context loss, cursor/endpoint violations, identity conflict, and job-shaped
identity defects stop the run under the current hard-stop contract. Aggregate
logical listing-page claims never exceed the reviewed Run Page Cap. Conditions
run sequentially, and each logical page claims budget before transport; bounded
transport retries for that logical page remain governed by the existing retry
policy rather than consuming another Page Depth slot.

## Non-job listing cards

Filter structurally identified OfferToday advertisement/banner cards before job
identity validation. The predicate must use positive non-job evidence such as
the advertisement/banner card shape; absence of identity alone is insufficient.
Ignored cards:

- never enter accepted identity sets, staging, or detail scope;
- do not produce `identity_issue` or stop pagination; and
- increment additive `non_job_cards_observed` on each production listing-page
  event and the task metric by summing accepted page observations.

A job-shaped row without required identity remains a hard identity issue. Keep
historical research serializers byte-compatible; expose new evidence only in
the production event/metrics projection allowed by the OfferToday production
contract. When a page mixes confirmed non-job cards with a job-shaped identity
defect, filter/count the cards first and then fail the page as `identity_issue`.

## Deduplication and classification evidence

The existing source-job identity and bulk staging path deduplicates overlap
across pages and keyword conditions. One source identity produces at most one
current-crawl listing/detail target and one published Job. Preserve every
observed OfferToday Source Classification Path by merging source-reported path
evidence before duplicate staging is suppressed; the selected classification is
not inferred from the keyword. Fixtures cover one identity observed under
multiple conditions/paths and assert one detail target with all evidence.

## Frontend behavior

On OfferToday only:

- scope selection is single-select;
- the execution step defaults to `100 / 3600`;
- Page Depth and Run Page Cap remain editable;
- live copy displays `36 keywords × depth`, estimated maximum, and cap validity;
- confirmation is disabled when the cap is below the estimate; and
- an under-budget existing Automation displays the server's structured update
  requirement instead of being mutated.

JobsDB and CTgoodjobs drafts, multi-select behavior, defaults, copy, validation,
and server review remain unchanged.

Cross-source regression fixtures serialize canonical adapter targets, resolved
scope, workload review, and outgoing request payloads before and after the
change. Their exact JobsDB/CTgoodjobs JSON projections must match; only
OfferToday fixtures may change.

## Rollout and rollback

Deploy decoder/runtime compatibility before or atomically with new plan
compilation. Once new plans exist, rollback may disable new authoring but must
not remove the ability to decode and execute already frozen keyword targets.
Rollback must never rewrite immutable plans into empty-keyword targets.

## Verification strategy

Use deterministic compiler/contract/runtime fixtures for normal verification.
Add a bounded opt-in live probe that compares the 36-target plan with the
historical category-only baseline, reports per-condition novelty/overlap, and
never writes crawl control or Job data. External totals are report-only because
the source is live; deterministic saved-response fixtures are the build gate.
Cross-source snapshot regressions prove that JobsDB and CTgoodjobs remain
unchanged.
