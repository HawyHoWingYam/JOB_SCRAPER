# Implementation-plan Tasks 1-8 requirement audit

## Audit boundary

- Audited on 2026-07-13 at `HEAD=507f85d5` on branch
  `codex/offertoday-it-coverage-20260702`.
- Authority: implementation-plan Sections 1-7, research-spec Phases A/B, the
  Plan 2 primary artifact index, the current source/tests, and current command
  output.
- Current offline provenance was captured at
  `2026-07-13T10:23:38.052222+00:00` with working-tree patch SHA-256
  `c703f5e7252a29fda0d990023311e426165aa3a8992ae3e1fc5bb965c8be7b85`.
- Verdict: every deterministic implementation requirement in Tasks 1-8 is
  proven. The Phase B live-only acceptance criteria remain pending until the
  two approved repeats and their decision artifacts are executed and replayed.

## Task 1: Freeze legacy replay before v2

| Requirement | Evidence | Status |
|---|---|---|
| Freeze the v1 canonical payload and hash | `test_census_candidate_hashes_sorted_compact_canonical_json` and the unchanged Plan 2 candidate manifest/hash | Proven |
| Route every legacy experiment to its exact verifier | `test_legacy_experiment_names_route_to_exact_frozen_verifiers` | Proven |
| Strictly replay baseline parent artifacts | `test_verify_live_run_accepts_foundation_baseline` and invalid-baseline rejection | Proven |
| Replay the 12 primary Plan 2 artifacts before live v2 work | 12/12 documented manifest hashes matched; 12/12 passed `verify-artifact`; 12/12 passed `verify-run` under the current checkout | Proven |
| Keep an explicit version boundary | `DiscoveryCandidateV2`, exact experiment-name dispatch, and `test_unknown_cursor_experiment_version_fails_closed` | Proven |
| Reject v1/v2 cross-parsing | `test_v1_and_v2_candidate_payloads_fail_closed_across_version_boundary` | Proven |

The historical artifacts remain valid rejected v1 evidence; no v1 meaning,
candidate hash, issue, or decision was rewritten.

## Task 2: Typed cursor, policy, transport, page, evidence, and candidate contracts

| Requirement | Evidence | Status |
|---|---|---|
| Exact scalar validation | `OfferTodayListingCursor`, `OfferTodayListingPageResult`, and malformed-scalar tests in `test_offertoday_listing_contract.py` | Proven |
| Preserve production defaults while accepting explicit size/cursor | `build_offertoday_listing_payload()` plus `test_listing_payload_includes_rcd_type_only_when_requested` | Proven |
| Build fresh payload dictionaries | `test_payload_builder_does_not_mutate_cursor_or_previous_payload` | Proven |
| Keep result and supplemental cohorts separate and immutable | `test_result_and_supplemental_rows_are_separate_frozen_copies` and typed cohort round-trip tests | Proven |
| Persist only hashed/redacted session evidence | `test_cursor_evidence_hashes_session_and_never_serializes_raw_value` and raw-session strict-replay rejection | Proven |
| Canonical v2 discovery candidate | `DiscoveryCandidateV2` and v2 hash/round-trip/tamper tests | Proven |

The production guard proves the default payload remains `pageSize=50`,
`rcdType=7`, with no cursor fields. Phase B explicitly supplies its separate
research policy; production adoption remains out of scope.

## Task 3: Condition-local cursor state machine

| Requirement | Evidence | Status |
|---|---|---|
| Explicit v2 policy with v1 compatibility | `OfferTodayListingRequestPolicy` and v1 observation compatibility tests | Proven |
| Cursor isolation per condition | `test_cursor_isolation_resets_page_one_for_each_condition` | Proven |
| Page 1 has no cursor; later pages carry the exact prior cursor | `test_cursor_mode_carries_exact_prior_response_cursor_to_next_page` | Proven |
| Advance only after successful validation/identity/observation | runner sequencing plus forged/failed-attempt strict-replay fixtures | Proven |
| Retry replays the same cursor, fingerprint, logical request, and context | `test_cursor_retry_replays_same_input_and_logical_request` and `test_pagination_bakeoff_retries_same_logical_page_in_same_runtime` | Proven |
| Reject rollover, missing cursor, drift, invalid resume, and cross-condition use | focused contract/runner negative tests | Proven |
| Keep supplemental identities separate and evidence-only | `test_supplemental_rows_are_evidence_only_and_not_product_staged` | Proven |
| Require terminal plus empty confirmation | `test_nonempty_cursor_confirmation_is_terminal_contract_violation` and strict replay | Proven |
| Stop before staging on cursor/identity/gap failures | `test_cursor_contract_failure_never_flushes_condition_staging` and supplemental conflict tests | Proven |
| Classify zero-new full pages | bake-off metrics and candidate rejection tests | Proven |
| Restart browser loss from page 1 and deduplicate | `test_browser_context_loss_restarts_condition_at_page_one_and_dedupes` | Proven |

## Task 4: Typed browser transport and lifecycle ownership

| Requirement | Evidence | Status |
|---|---|---|
| Typed listing transport while retaining legacy JSON transport | `fetch_listing_page()` and `fetch_listing_json()` | Proven |
| Own successful HTTP status/final URL and copied payload | `OfferTodayListingTransportResult` tests | Proven |
| Generate non-sensitive context identity without cursor state | `test_fetch_listing_page_returns_typed_context_evidence_without_cursor_state` | Proven |
| Implement shared-variant, condition-local, and restart-each-page lifecycles | `test_run_pagination_bakeoff_honors_frozen_order_and_runtime_lifecycles` | Proven |
| Close every runtime on success/failure/rejection/exception | live-service cleanup, hard-stop, unexpected-error, and shared-close-error tests | Proven |
| Preserve CSRF/cookie and auth/WAF/IP classifications | existing browser-runtime regression suite | Proven |

## Task 5: V2 events, artifacts, conservation, and strict replay

| Requirement | Evidence | Status |
|---|---|---|
| Persist exact v2 page-attempt and condition-boundary evidence | typed page evidence and pagination artifact fixtures | Proven |
| Exclude raw secrets before and during export | redacted serializers and `test_pagination_bakeoff_rejects_raw_session_leak` | Proven |
| Independently replay logical/physical counts, cursor continuity, IDs, cohorts, duplicates, overlap, drift, and conservation | `pagination_stage_gate.py` recomputation plus derived-count/drift/cursor/cohort tamper tests | Proven |
| Enforce ordering, retries, isolation, budgets, no-write evidence, snapshots, and terminal state | full replay fixture and missing/duplicate/reordered/changed-parent/write-evidence negative tests | Proven |
| Reject forged hashes, changed cursor inputs, missing attempts, duplicate sequences, and leaked session values | dedicated pagination stage-gate tests | Proven |

Both generic artifact hashes and the experiment-specific verifier are required;
neither is treated as a substitute for the other.

## Task 6: Frozen five-variant bake-off and decision engine

| Requirement | Evidence | Status |
|---|---|---|
| Exact endpoint/category/variant controls | `pagination_bakeoff_controls_payload()` and exact-payload test | Proven |
| Ten logical pages per condition and one transient retry | frozen constants and exact policy/budget tests | Proven |
| Zero detail and no-op listing staging | live service/CLI request budget and no-write replay tests | Proven |
| Pre-response deterministic randomization | `build_bakeoff_order()` and deterministic/category-randomized order test | Proven |
| Recompute all frozen metrics, including page-size and reported-total drift | `summarize_variant()` plus drift-metric tests and strict replay | Proven |
| Freeze both duplicate-reduction thresholds | exact threshold payload test and individual rejection tests | Proven |
| Enforce union/cost, Jaccard, integrity, and zero-new gates | decision tests for every individual rejection reason | Proven |
| Fail closed on ties, input-order drift, multiple passers, and no candidate | tie/order/no-candidate tests | Proven |

The exact order for seed `20260713` was recomputed after the final code changes
and still matches the pre-registered two-repeat order in
`deterministic-review.md`.

## Task 7: Live/offline CLI commands

| Requirement | Evidence | Status |
|---|---|---|
| Implement the three new commands without reusing v1 semantics | parser/dispatch and CLI tests for `pagination-bakeoff`, `compare-pagination`, and `freeze-discovery-candidate` | Proven |
| Require exactly two matching baselines and current-database equality before browser startup | baseline gate and database-drift-before-browser tests | Proven |
| Freeze 150 logical, 300 physical, zero-detail, zero-write budget | exact request-budget artifact and CLI tests | Proven |
| Persist order, controls, provenance, snapshots, and no-write evidence | successful live-command fixture plus strict replay | Proven |
| Keep comparison offline and bind immutable verified parents | offline comparison and mismatched/reused-parent tests | Proven |
| Freeze only exactly one accepted cursor candidate | comparison/candidate verifier and fail-closed freeze tests | Proven |
| Distinguish accepted/rejected/hard-stop/invalid-evidence exits | `0`, `3`, `4`, and `5` exit-code tests | Proven |
| Export strict-replayable partial evidence on hard/unexpected failure | hard-stop, unexpected-error, and shared-close-error artifact tests | Proven |

## Task 8: Deterministic verification and live gate

Current deterministic evidence:

- expanded Phase A/B focused matrix: `954 passed, 16 warnings`;
- complete backend suite: `1221 passed, 63 warnings`;
- focused production-default guards: `3 passed`;
- scoped Ruff: passed;
- scoped `py_compile`: passed;
- `git diff --check`: passed with line-ending warnings only;
- Plan 2 primary artifact index: 12/12 hashes, 12/12 generic verification,
  and 12/12 strict replay passed; and
- current provenance and exact order seed/order are frozen before Phase B.

The user explicitly approved live execution after this deterministic evidence
was explained. The remaining Task 8 evidence is live-only:

1. capture two fresh matching baselines for repeat 1;
2. run and verify repeat 1;
3. capture two new fresh matching baselines for repeat 2;
4. run and verify repeat 2;
5. compare offline and independently recompute;
6. freeze exactly one accepted v2 candidate, or persist an explicit
   no-candidate decision; and
7. stop before Phase C in either case.
