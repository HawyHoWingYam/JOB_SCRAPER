# OfferToday Plan 2 Census Decision

**Date:** 2026-07-13
**Decision:** Rejected for Plan 3 entry
**Failed gate:** `fixed_cohort_jaccard`
**Production defaults:** Unchanged

## Evidence Integrity

- Plan 2 deterministic slice: `744 passed`.
- Complete backend suite: `1077 passed`.
- Production-default guard tests: `3 passed`.
- Generic artifact verification: 29/29 valid.
- Strict live-run replay: 11/11 valid.
- Range `git diff --check`: clean.
- Plan 2 range changed no migration, model, Compose, or environment-default file.
- Runtime artifacts remain ignored and uncommitted.

The comparison was independently recomputed from the six input artifacts. The rerun produced the same metrics and exit code `3` (accepted evidence, rejected decision).

### Primary Artifact Index

All paths are relative to `backend/runtime/offertoday-research/` and contain verified `manifest.json`, `observations.jsonl`, and provenance evidence.

| Experiment | Run ID / path | Manifest SHA-256 |
|---|---|---|
| Accepted smoke | `2984cc00-c79e-4664-8734-e5ffebe4722e` | `abe0bd7e83f52a7dfe6343faa67f748cdeb7ca593e17b2a58bfd54161dacdb33` |
| Calibration | `d1432f7a-fb5b-4396-b054-d0d5b0b89927` | `2eeb0c1f8b8a6155d223e06af5d836d5c5303274b511a2a35d5578795bac8a50` |
| Pilot | `a697421a-9d0a-4928-863d-ed5273dd5330` | `e3f30fffc1b74b6233e430c9aecf721c3fc51ef3076974fe6556b8d39e18d6dd` |
| Candidate | `fd616ae7-3870-438f-804e-e8728058b242` | `1760e938d8b6b23992c5d401e99d0dd1fea85df9daf5b08f59b6b43dd52fe287` |
| Census 1 | `02786783-a668-425d-8c36-a2b785355244` | `b4da1947ad9e0c9f2b5cd3f44765b003965996e09b5eac7ceacabb00e6ce0987` |
| Census 2 | `62a9ad89-d80a-4ff2-a253-885d5912409c` | `07670fd6ac4b1172d22b78fd605b52a0fdedcec28a3489fcb839c2b4486dcb8a` |
| Census 3 | `d34a5cc8-2a82-46c0-82df-5f8fa1420361` | `9fd2813f68f2be798dabfa4b80d192282f8780ac11e77b6bdd774560029a0be1` |
| Fixed repeat 1 | `23be391e-8961-44ea-9a1a-f7ff5776d2e4` | `fcf10f61ef8748e0696aa24a7bafb74f35cfdb41e76ab593c6718ba7f117e8ab` |
| Fixed repeat 2 | `83b62928-7161-40ea-9f75-000921183ec6` | `abdbb76d05919486b2d7cf3544ac023b60ec75d9dcc5487586da2487b4092308` |
| Fixed repeat 3 | `f51583ec-5cc4-4c2f-86bb-b017ed4a1845` | `eca1b03dac9ecf6cd8c2f7e10a6c9c97109a11eb9e15d3a9009c8385bc5aef3f` |
| Comparison | `a41eddaf-0f51-4921-936d-588b16f29ad0` | `301a6f2d31744d1b79cfeea992d58989d1b4fb3a9becde63bd192458e8875d17` |
| Independent recomputation | `b1d12701-d74f-463e-9acd-ee30223d4cd1` | `d99362b2f32a5446d0d69b9677ad462999335d6740b01aa635448a52ab0ff7d6` |

## Frozen Candidate

- Candidate run: `fd616ae7-3870-438f-804e-e8728058b242`
- Candidate hash: `4940cd7af07150decb2a9431966f621db14d2ab6caccdf677aa1c2839fb46292`
- Endpoint: `/wapi/geek/recommend/search/list`
- `rcdType`: omitted
- Categories: all 31 frozen top-level IDs
- Fixed cohort: `(118000, 112000, 127000)`
- Requested page size: 50
- Max pages per condition: 500
- Empty confirmation: required
- Session mode: `fresh-headless`

Rejected calibration alternatives included `search/list + rcdType=7`, `recommend/list + rcdType=7`, and `recommend/list` without `rcdType`. The selected candidate was evidence-backed relative to those variants, but later live evidence invalidated the assumed stateless pagination contract.

## Accepted Bounded Smoke

- Run: `2984cc00-c79e-4664-8734-e5ffebe4722e`
- Captured: `2026-07-12T08:35:18.428068+00:00`
- Listing requests: 2
- Frozen distinct targets: 20
- Detail attempts: 20
- Success: 20
- Terminal: 0
- Unattempted: 0
- Valid title/company/description/identity: 20/20 each
- Product data unchanged: true

All listing rows used `jobId_fallback`; raw `encryptJobId` was absent. This smoke proves the fallback route can retrieve valid details. It does not satisfy the separate 99% Plan 4 detail gate.

## Calibration and Pilot

- Calibration run `d1432f7a-fb5b-4396-b054-d0d5b0b89927`: accepted, 20 logical/physical attempts, 0 details.
- Pilot run `a697421a-9d0a-4928-863d-ed5273dd5330`: accepted, 31/31 conditions, 91 logical/physical attempts, 0 details, conservation difference 0.

## Full Census Results

| Run | Captured (UTC) | Distinct IDs | Requests | Duration (s) | Set hash |
|---|---|---:|---:|---:|---|
| `02786783-a668-425d-8c36-a2b785355244` | `2026-07-12T15:31:57.510867+00:00` | 5,563 | 1,382 | 5,828.264 | `32b9a712dabf1e04aa930697592b41cb99073fd9ac69951111deb4600f49e53a` |
| `62a9ad89-d80a-4ff2-a253-885d5912409c` | `2026-07-13T00:36:16.516419+00:00` | 5,581 | 1,382 | 5,857.461 | `2493c0d09277a1de0ab0324fda00a38fb5d426bcad7626a8a105115b51ec466b` |
| `d34a5cc8-2a82-46c0-82df-5f8fa1420361` | `2026-07-13T02:17:46.216237+00:00` | 5,599 | 1,382 | 5,875.690 | `eccc7b54219bce228dbdbe8e6f9f0484471eaae100712b406345002f67bbe516` |

- Time-window span: `38,748.705370` seconds.
- Unique-count CV: `0.0026333880051422807` (passes `<= 0.05`).
- Census union: 6,190 IDs.
- Census intersection: 4,946 IDs.
- Union hash: `2af9090b5dc67f8ccf11564fc8135f7ebd7dac1d59ebed02f66836ef38b42fb2`.
- Pairwise Jaccard: `0.866979`, `0.849238`, `0.868940`.
- Pairwise added/removed counts: `406/388`, `473/437`, `401/383`.
- Requests per union ID: `0.6697899838449112`.
- Seconds per union ID: `2.837062242810986`.
- Every census: 31 natural condition outcomes, 0 detail requests, 0 unresolved gaps, 0 identity conflicts, 0 conservation difference, 0 unclassified failures.

## Fixed-Cohort Results

| Run | Captured (UTC) | Distinct IDs | Requests | Set hash |
|---|---|---:|---:|---|
| `23be391e-8961-44ea-9a1a-f7ff5776d2e4` | `2026-07-13T02:31:10.648107+00:00` | 611 | 138 | `4ee6a881df84bcb4f48dd4341c47caf8f31bbd6fdb63e7ec98a9fbabbf830de5` |
| `83b62928-7161-40ea-9f75-000921183ec6` | `2026-07-13T02:44:56.123576+00:00` | 609 | 138 | `3f4534dc3ee805c26176804f178bca6eddd50aad775ebf13ad1c47182c6ca75a` |
| `f51583ec-5cc4-4c2f-86bb-b017ed4a1845` | `2026-07-13T02:58:30.490668+00:00` | 608 | 138 | `e25e888fba50279ae5134fe29bf56894d1a37999f0277d899f68d23b36e9dd82` |

- Short-window span: `1,639.842561` seconds.
- Fixed union: 671 IDs.
- Fixed intersection: 548 IDs.
- Fixed union hash: `040133067ac38820e8f34925e9af3cbd2fcc8f1e9b2a316ac1a38e8f999564a2`.
- Pairwise Jaccard: `0.868300`, `0.878274`, `0.875193`.
- Pairwise added/removed counts: `42/44`, `38/41`, `40/41`.
- IDs seen in only one fixed run: 22, 22, and 18 respectively.

The required minimum fixed-cohort Jaccard was `0.95`; observed minimum was `0.8683001531393568`.

## Root-Cause Evidence

Each fixed category returned 45 non-empty pages of 10 rows plus one empty confirmation page. Cross-page duplication was severe:

| Category | Raw rows | Distinct range | Duplicate range |
|---|---:|---:|---:|
| `118000` | 450 | 237-239 | 211-213 |
| `112000` | 450 | 234-236 | 214-216 |
| `127000` | 450 | 136-138 | 312-314 |

For `118000`, page 3 repeated 8/10 IDs from page 2, while later pages sometimes added zero or one ID. `data.total` changed during the same pagination chain.

Live observation of OfferToday's own UI established the missing contract:

1. UI page 1 sends `pageSize=10`.
2. Response page 1 returns `sessionId`, `supplePage`, `suppleAmount`, and `suppleType`.
3. UI page 2 sends the same values back.
4. The crawler sends none of those cursor fields and requests `pageSize=50`, although the response still contains only 10 rows.

This is a confirmed crawler defect, not merely normal job churn. The current empty-page result is an exhaustion signal for a stateless recommendation sequence, not proof of complete category enumeration.

## Decision

Plan 3 entry is rejected. Passing gates were:

- all three censuses accepted;
- unique-count CV;
- zero unresolved gaps;
- zero identity conflicts;
- zero conservation difference; and
- zero unclassified failures.

The failing gate was:

```text
fixed_cohort_jaccard: observed 0.8683001531393568 < required 0.95
```

Production defaults remain unchanged. The next authorized work is the cursor-correct pagination research and implementation described in `docs/specs/2026-07-13-offertoday-completeness-and-stability-research-spec.md`. Full-census repetition, keyword expansion, higher concurrency, and broad detail draining must not proceed until the bounded cursor bake-off passes.
