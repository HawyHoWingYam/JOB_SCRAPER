# Expand OfferToday listing coverage with keyword query targets

## Goal

Restore OfferToday listing coverage that is only discoverable through keyword
searches while preserving truthful crawl scope, bounded execution, and the
existing published dispatch-plan contract.

## User value

An operator selecting an OfferToday classification can collect jobs that the
source omits from its plain category browse results without manually creating
many separate crawls or silently changing JobsDB and CTgoodjobs behavior.

## Confirmed facts

- The completed OfferToday task
  `3c2d5886-9d06-48f1-8d7f-ef481072b315` selected classification `118000`
  with `page_depth=200` and `run_page_cap=200`. Its only Query Target used an
  empty keyword, reached natural exhaustion on page 46, observed 274 distinct
  source job identities, skipped 249 existing jobs, and staged 25 new listings.
- A bounded live smoke on 2026-07-27 confirmed that OfferToday still exposes
  materially different result sets through keyword search. Reported totals
  included category-only `118000=389`, keyword-only `engineer=800`, and hybrid
  `118000+engineer=697`; the tested keyword/hybrid first pages had no identity
  overlap with the category-only first page.
- A second bounded live smoke sent one page for every hybrid `118000+A` through
  `118000+Z` and `118000+0` through `118000+9`. All 36 keywords returned API
  code `0` with nonempty results. `A` and `a` reported the same total but
  returned different first-page rankings/identities, so the sweep uses uppercase
  as its deterministic canonical representation without claiming case-equivalent
  pagination.
- A production-contract probe of `118000+A` found 12 rows in `resultList`, of
  which 10 were job rows and 2 were structurally different banner/advertisement
  cards with no job identity. The current strict listing runner classifies the
  entire page as `identity_issue` when those cards are present, so the 36-target
  sweep cannot paginate successfully until non-job card handling is explicitly
  defined.
- Commit `c01de07f` introduced OfferToday IT root/child expansion, a default IT
  keyword pack, and hybrid keyword probes. Commit `d66fc820` later bound normal
  crawls to published Source Classification plans.
- The current OfferToday adapter compiles one selected classification into one
  bounded empty-keyword category target at
  `backend/app/source_classifications/adapters/offertoday.py:161-179`.
- The current OfferToday search-space helper retains keyword-only and
  category-plus-keyword condition support at
  `backend/app/sources/offertoday/search_space.py:284-355`.
- Listing runtime review requires `query_target_count * page_depth <=
  run_page_cap` at `backend/app/crawl_control/listing_runtime.py:57-70`.
  Therefore additional keyword Query Targets cannot be appended to the prior
  `200/200` plan without changing its reviewed workload shape.
- Generic compilation, frozen scope persistence, and workload preview already
  support multiple Query Targets for one Source Classification. The current
  OfferToday public target parameters are the source-specific restriction: they
  require `endpoint='browse'` and `keyword=''`.
- The 36 replacement targets use OfferToday's production `search/list`
  response-cursor contract with `rcd_type=None`; they cannot reuse the former
  browse-target parameter contract (`endpoint='browse'`, `rcd_type=7`).
- Current authoring stores Page Depth and Run Page Cap as independent fields,
  while the system listing cap defaults to `5000`. Under the confirmed
  OfferToday-only cardinality (one classification and exactly 36 targets), the
  exact reviewed maximum is `36 * page_depth`; the separately editable Run Page
  Cap must be at least that estimate.
- At planning time the database contains one historical OfferToday listing task,
  already `completed`, and no queued, running, paused, or otherwise resumable
  OfferToday task. Historical empty-keyword records can remain read-only evidence;
  no in-flight task migration is required.

## Requirements

- R1. The change is OfferToday-specific. JobsDB and CTgoodjobs adapters,
  authored scope resolution, dispatch-plan contents, request payloads, and
  runtime behavior must remain unchanged.
- R2. OfferToday keyword coverage must be represented by explicit frozen Query
  Targets in the reviewed dispatch plan; the runner must not invent hidden
  keyword requests after plan confirmation.
- R2a. The MVP uses hybrid targets only: every keyword target must retain the
  selected OfferToday classification in `jobFunctionCodes`. Categoryless
  keyword-only targets are prohibited.
- R2b. The reusable Classification Keyword Sweep is the deterministic 36-item
  set `A` through `Z` followed by `0` through `9`, with one hybrid Query Target
  per keyword for each eligible selected OfferToday classification.
- R2c. Every selected OfferToday top-level Source Classification automatically
  receives the Classification Keyword Sweep. The operator selects classifications
  only; there is no separate keyword toggle or keyword authoring step. IT is the
  first live-validated classification, not a product-scope restriction.
- R2d. Newly prepared OfferToday listing plans contain no empty-keyword category
  target. The 36-target Classification Keyword Sweep replaces, rather than
  supplements, the former ordinary category browse target.
- R2e. An OfferToday listing task selects exactly one top-level Source
  Classification. Authoring and backend validation reject zero or multiple
  classifications for this source. JobsDB and CTgoodjobs retain their existing
  selection cardinality.
- R3. Every keyword Query Target must have an explicit search family,
  classification attribution policy, keyword, endpoint contract, stable
  fingerprint, and deterministic order.
- R4. Page depth and aggregate Run Page Cap must remain truthful for all frozen
  Query Targets; plan preview must expose the expanded workload before
  confirmation.
- R4a. OfferToday Page Depth applies independently to each of the 36 keyword
  Query Targets and defaults to 100. OfferToday imposes no product-level maximum
  Page Depth beyond requiring a positive integer; Run Page Cap remains the
  explicit finite aggregate guard and defaults to 3,600. JobsDB and CTgoodjobs
  retain their existing source behavior and input limits. Shared wire/storage
  integer-safety bounds remain technical constraints rather than an
  OfferToday product limit.
- R4b. The existing OfferToday authoring page retains separately editable Page
  Depth and Run Page Cap inputs. It immediately recalculates and displays the
  36-target estimated maximum (`36 * page_depth`) and budget validity whenever
  either input changes; JobsDB and CTgoodjobs authoring controls retain their
  current behavior.
- R4c. OfferToday authoring rejects confirmation when Run Page Cap is less than
  `36 * page_depth`. A smaller aggregate cap must not create an order-dependent
  partial sweep in which later keywords receive no reviewed budget.
- R4d. Only OfferToday is exempt from the generic 5,000-page system listing cap.
  Its explicitly entered and reviewed Run Page Cap remains the finite hard bound
  enforced by dispatch and runtime. JobsDB and CTgoodjobs continue to use the
  existing generic 5,000-page system cap.
- R5. Results from overlapping OfferToday Query Targets must retain all observed
  Source Classification Path evidence while deduplicating detail work by source
  job identity under the existing listing/detail contracts.
- R6. Existing OfferToday automations and one-off authoring remain compatible;
  any coverage expansion must be visible rather than silently multiplying a
  previously reviewed workload.
- R6a. An existing OfferToday Automation whose saved Run Page Cap is below
  `36 * page_depth` is not silently rewritten or dispatched. It is retained,
  shown as requiring a budget update, and becomes dispatchable only after the
  operator reviews and saves valid limits on the existing authoring page.
- R7. Tests must lock down OfferToday target compilation and cross-source
  isolation, including explicit assertions that JobsDB and CTgoodjobs plans are
  byte-for-byte behaviorally unchanged for equivalent existing inputs.
- R8. OfferToday rows that are structurally identifiable as non-job
  advertisement/banner cards are ignored without failing or stopping the query.
  Their count is retained as `non_job_cards_observed` in production listing
  observations and aggregated task metrics. A job-shaped row that lacks required
  identity remains an identity failure.
- R9. The 36-keyword sweep continues after natural exhaustion or a retained
  per-keyword Page Depth cap. It stops the entire task on WAF/auth/IP blockers,
  exhausted transport recovery, browser-context loss, identity conflict, or a
  job-shaped identity defect. Previously completed condition progress remains
  observable and resumable only under the existing immutable-plan rules.

## Acceptance Criteria

- [x] Selecting any OfferToday top-level Source Classification automatically
  freezes exactly 36 ordered hybrid targets (`A`-`Z`, then `0`-`9`), each
  carrying that classification.
- [x] OfferToday authoring accepts exactly one classification and rejects
  multi-classification requests before dispatch-plan confirmation without
  changing JobsDB or CTgoodjobs authoring behavior.
- [x] No newly prepared OfferToday listing plan or runtime request contains an
  empty keyword.
- [x] The OfferToday preview reports expanded target count, page depth,
  estimated maximum pages, and aggregate cap consistently before confirmation.
- [x] Editing OfferToday Page Depth or Run Page Cap updates the displayed
  36-target estimate and validation state immediately on the existing authoring
  page.
- [x] An OfferToday plan with Run Page Cap below `36 * page_depth` is invalid and
  cannot be confirmed; an equal or larger cap passes this workload check.
- [x] OfferToday plans are not rejected by the generic 5,000-page system cap and
  cannot exceed their reviewed operator Run Page Cap; equivalent JobsDB and
  CTgoodjobs plans still enforce the unchanged 5,000-page system cap.
- [x] OfferToday defaults Page Depth to 100 and Run Page Cap to 3,600, accepts
  positive integer OfferToday Page Depth values without a product-level maximum,
  rejects unsafe/non-representable integer arithmetic, and uses
  `36 * page_depth` as estimated maximum pages.
- [x] A bounded opt-in live comparison reports per-condition overlap/novelty and
  demonstrates keyword-only coverage beyond the historical category-only
  baseline; deterministic fixtures, not external totals, remain the CI gate.
- [x] Runtime consumes only the frozen OfferToday Query Targets and cannot exceed
  the reviewed aggregate Run Page Cap.
- [x] Repeated source identities across category/keyword targets do not create
  duplicate published Jobs or duplicate detail attempts.
- [x] Advertisement/banner cards mixed into OfferToday `resultList` neither
  become listings nor stop pagination, and ignored-card counts are observable;
  job-shaped identity defects still follow the existing failure contract.
- [x] Natural exhaustion and retained Page Depth caps advance to the next
  keyword, while true access/transport/identity failures stop the sweep with a
  structured reason and preserve prior condition observations.
- [x] JobsDB and CTgoodjobs adapter, dispatch-plan, request, and focused runtime
  regression suites pass without production-code changes to those sources.
- [x] Existing under-budget OfferToday automations remain stored but do not
  dispatch until an operator explicitly saves valid 36-target limits; no
  automatic 36-fold cap expansion occurs.
- [x] Historical category-only OfferToday task records remain readable without
  being rewritten into the new 36-target scope.

## Out of scope

- JobsDB or CTgoodjobs coverage, query semantics, payloads, and runtime changes.
- Job detail parsing, enrichment, JobBrowser presentation, and canonical Job
  Taxonomy changes.
- Unreviewed unlimited keyword crawling or bypassing dispatch-plan workload
  validation.

## Planning status

No product decision remains open. Technical design and implementation ordering
are recorded in `design.md` and `implement.md`; implementation remains blocked
on user review.
