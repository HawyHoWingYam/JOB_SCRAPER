# OfferToday Phase C research infrastructure design

## 1. Scope decision

This child implements Phase C research machinery but does not execute it live and does not freeze a discovery candidate. It is an explicit sequencing exception to the original Phase B-to-C gate: unresolved Issues #4/#5 remain attached to all downstream evidence but do not prevent deterministic implementation or later task creation.

The implementation must allow a future authorized run to produce valid rejected or inconclusive evidence. A page cap, unstable set, or unverified cursor contract is an outcome to preserve, not an error to hide and not an implicit acceptance.

## 2. Current boundaries

- `listing_contract.py` owns the current search-shaped cursor parser and v2 page evidence.
- `listing_runner.py` builds one generic payload, selects a URL from `condition.endpoint`, and applies the same parser to both URLs.
- `category_registry.py` owns 31 flat L1 nodes; `search_space.py` separately owns a hard-coded IT descendant tuple.
- `offertoday_research_live_service.py` owns bounded research orchestration and already supports a no-op staging sink.
- `offertoday_research_census.py` owns live/offline command dispatch, baseline gates, artifact export, and exit codes.
- `stage_gate.py` routes exact experiment names to semantic verifiers; pagination-specific replay lives in `pagination_stage_gate.py`.

The new flow is:

```text
versioned endpoint contracts + official category catalog
                         |
                         v
             immutable probe plan and budget
                         |
          baseline gate -> research service -> no-op sink
                         |                 |
                         +---- page evidence + no-write snapshots
                                           |
                                           v
                               generic artifact verification
                                           |
                                           v
                                experiment strict replay
                                           |
                                           v
                         offline partition comparison report
                         (no candidate and no production path)
```

## 3. Endpoint contract model

### 3.1 Registry and adapters

Add an immutable `OfferTodayListingEndpointContract` registry in `listing_contract.py`. Each entry owns:

- a stable contract ID and exact schema version;
- the endpoint kind and exact URL;
- allowed probe `rcdType` values;
- request field rules;
- result and supplemental cohort field names;
- cursor capability and cursor field decoder;
- terminal and empty-confirmation field rules; and
- a canonical contract hash.

Initial contracts:

| Contract | Confirmed behavior | Cursor status |
|---|---|---|
| `recommend-search-list-v1` | Existing `resultList`, `suppleRcdList`, `pageSize`, `hasMore`, and Phase B cursor fields | Known search-shaped response cursor; still subject to Issues #4/#5 |
| `recommend-list-envelope-v1` | Real fixture confirms `resultList`, `pageSize`, `hasMore`, and diagnostic `total` | `unverified`; no search cursor or terminal fields are borrowed |

The initial Phase C probe catalog uses omitted `rcdType` only. Existing production `rcdType=7` remains unchanged but is not promoted into a Phase C accepted contract merely because legacy code uses it.

### 3.2 Compatibility path

The existing `parse_offertoday_listing_page_result()` behavior remains the default when no Phase C contract is supplied, preserving Phase A/B IDs, serialized page evidence, and strict replay. An explicit contract ID selects an endpoint-specific adapter.

Extend `OfferTodayListingRequestPolicy` with an optional contract identity. When absent, its canonical identifiers remain byte-for-byte compatible. When present, the contract ID/hash participates in Phase C logical request identity. Phase C execution wrappers store contract identity alongside unchanged v2 page evidence, avoiding a schema mutation to historical page artifacts.

Before parsing, the runner validates:

- contract endpoint equals `condition.endpoint`;
- transport response URL equals the contract URL when URL evidence is available;
- request fields and `rcdType` match the contract;
- cursor use is allowed by that contract; and
- a browse response is never decoded with the search adapter or vice versa.

Any violation becomes `endpoint_contract_violation` before staging. The browse envelope contract can support a bounded field-presence probe, but it cannot claim cursor exhaustion. A later live finding creates a new browse contract version rather than mutating v1.

## 4. Official category and partition catalogs

### 4.1 Source normalization

Use the official snapshot from commit `ed03f114fb8bc73eeb11139d82325a7944802701` as source evidence without restoring its deleted `.debug/` files. Normalize the English `POSITION` hierarchy into the existing `OfferTodayCategory` fields only; do not invent `name_en` or `name_zh` fields.

The registry preserves:

- 31 ordered L1 nodes;
- 462 ordered L2 nodes;
- exactly one same-code `All ...` alias under each L1 node; and
- 431 query-distinct leaf nodes where `child.code != child.parent_code`.

Keep existing flat APIs and L1 iteration behavior stable. Add explicit recursive/catalog helpers rather than changing the output shape used by `SourceCategoryRegistry`.

### 4.2 Partition identity

`partition_research.py` owns an immutable `OfferTodayPartitionDefinition` and catalog builders. A partition ID hashes:

- partition schema version;
- kind (`top_level_category` or `leaf_category`);
- category code, name, parent code, and level; and
- exact query filter payload.

The category catalog preserves same-code aliases, but the partition catalog excludes them because they generate the same request as the parent. Catalog order is official source order: all L1 partitions first, then query-distinct leaves in parent/child order. The catalog and ordered partition list each have canonical SHA-256 hashes.

Date, publish-time, language, and location definitions are absent from v1. Adding one requires a later contract artifact and a version bump.

## 5. Probe and comparison contracts

### 5.1 Pure models

`partition_research.py` contains pure, strict dataclasses and functions for:

- endpoint probe plans and executions;
- partition probe plans and executions;
- exact plan-derived request budgets;
- normalized page/condition outcomes;
- partition contribution and overlap calculations;
- last-100-successful-request marginal curves; and
- comparison decisions and canonical payload hashes.

Probe definitions combine an endpoint contract, one partition, an explicit pagination policy, pacing/terminal policy, and exact budget. No implicit production defaults are read when constructing a research plan.

### 5.2 Budget shape

`probe-endpoints` uses a fixed v1 matrix with the two explicit endpoint contracts, omitted `rcdType`, at most three logical pages per contract, at most three physical attempts per page, zero detail, and zero product writes. This is a contract-shape probe and cannot claim exhaustion merely because it ended within the budget.

`probe-partitions` requires repeated explicit `--partition-id` inputs and an explicit `--max-pages-per-condition` in the bounded range `1..10`. The budget is derived exactly from selected conditions and retry limits. There is no implicit `all` selection. A later live task must review the exact IDs and budget before use.

Both commands require `--confirm-live-research`, exactly two distinct matching baseline artifacts, a current-database recheck before runtime construction, and a `ResearchNoopListingStagingSink`.

### 5.3 Command parents

- `probe-endpoints` accepts a strict-valid Phase B comparison artifact as provenance even when it is valid rejected. Rejection does not block the probe plan.
- `probe-partitions` requires a strict-valid endpoint-probe parent and may consume an inconclusive endpoint result; each resulting condition remains ineligible for retention unless its own contract and terminal gates pass.
- `compare-partitions` accepts one or more strict-valid partition-probe artifacts, constructs no database/browser/service dependency, and requires distinct parent runs with matching catalog, contract, policy, and baseline-state hashes.

### 5.4 Comparison semantics

The active reference denominator is the exact distinct canonical `jobId` union from the verified probe inputs, never `data.total` or a sum of row counts. In deterministic catalog order, recompute for every partition:

- set size and union/intersection hashes;
- overlap with prior cheaper conditions;
- unique contribution IDs and ratio to the active reference union;
- logical/physical request cost per contributed ID;
- exact gaps, identity conflicts, and conservation difference; and
- the marginal new-ID curve, including a last-100 window only when 100 successful requests exist.

A partition is numerically retainable at contribution ratio `>= 0.005`. High-value exceptions come only from a versioned in-code override catalog containing partition ID and rationale; v1 is empty. Cursor-confirmed terminal state, required empty confirmation, zero gaps/conflicts/conservation difference, and verified endpoint contract remain independent hard acceptance fields. Marginal saturation never changes them.

The comparison artifact can be accepted as a valid report even when every partition is rejected. CLI exit codes retain the existing convention: `0` for a completed accepted research decision, `3` for valid incomplete/rejected evidence, `4` for a live hard stop, `5` for invalid evidence, and `2` for usage errors. No outcome creates `DiscoveryCandidateV2`.

## 6. Artifact and replay design

Create `partition_stage_gate.py` rather than extending the already large pagination verifier. Route these exact names from `verify_live_research_run()`:

- `endpoint-contract-probe-v1`;
- `partition-probe-v1`; and
- `partition-comparison-v1`.

Each artifact contains standard manifest/provenance files plus one typed JSON payload (`endpoint-probe.json`, `partition-probe.json`, or `partition-comparison.json`). Payloads include exact contract/catalog hashes, plan, budget, parent projections/hashes, normalized page evidence, no-write snapshots, and decisions.

Comparison artifacts embed canonical parent projections and manifest hashes so strict replay can recompute offline without trusting filesystem paths. Parent commands still require generic plus strict verification before projection.

The strict verifier:

1. runs generic hash/secret verification;
2. validates exact manifest, event, and payload fields;
3. reconstructs typed contracts, plans, page evidence, and parent projections;
4. recomputes canonical hashes, budgets, no-write invariants, contribution metrics, and decisions;
5. rejects any mismatch or unknown version; and
6. preserves valid rejected/inconclusive evidence as semantically valid.

Raw session/cursor values never enter payloads. Existing hashed cursor evidence is reused. Tests must re-export semantically modified payloads so generic hashes pass while strict replay fails.

## 7. Service and CLI boundaries

`OfferTodayResearchLiveService` gains separate endpoint and partition probe methods. It receives a frozen plan, injected runtime factory, observation service, and no-op sink; it does not choose contracts, partitions, budgets, or defaults.

`offertoday_research_census.py` owns:

- argument parsing and explicit live confirmation;
- parent generic/strict verification;
- matching-baseline and current-database gates;
- run/event lifecycle and pre/post snapshots;
- invocation of the service with frozen inputs;
- artifact export and immediate generic/strict verification; and
- exit-code mapping.

`compare-partitions` stays entirely offline and must be tested with constructors that raise if any session, repository, runtime, observation service, or staging dependency is touched.

The legacy `offertoday_endpoint_probe.py` remains non-authoritative and is not imported by the new implementation.

## 8. Production compatibility

- No database migration, API route, frontend change, Compose change, or environment change is needed.
- `build_offertoday_listing_payload()` defaults remain `pageSize=50`, `rcdType=7`, and no cursor fields.
- Production listing conditions and standalone crawl continue without an explicit Phase C request policy.
- Existing v1/v2 experiment names and payload schemas remain unchanged.
- Existing `freeze-discovery-candidate` remains a Phase B command and is neither widened nor invoked by this child.
- The full official hierarchy may replace the duplicate IT code list internally only when golden tests prove identical production order and values.

## 9. Rollback and failure boundaries

- All new runtime behavior is opt-in behind new commands and explicit contract IDs; rollback is removal of the opt-in routes without touching historical artifacts.
- A contract violation, auth/WAF/IP stop, browser loss, identity problem, gap, conservation difference, budget overrun, baseline drift, or product snapshot drift stops the current live-capable command and preserves a strict-replayable prefix.
- If a planned edit overlaps unrelated worktree changes, isolate the hunk or stop for user direction.
- Runtime artifacts stay ignored and uncommitted. This child creates no real runtime artifact because live commands are not executed.
