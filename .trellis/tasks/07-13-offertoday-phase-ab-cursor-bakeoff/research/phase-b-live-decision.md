# Phase B live pagination decision

## Decision

- **Outcome:** valid evidence, no accepted discovery candidate.
- **Comparison exit:** `3` (`valid-but-rejected`).
- **Selected variant:** `null`.
- **Production defaults:** unchanged.
- **Next phase:** stopped before Phase C, as required by the Phase B gate.

Every artifact below passed generic hash verification and experiment-specific
strict replay. The second comparison independently recomputed the first and
produced a byte-identical `comparison.json` with SHA-256
`00d6be50471c05e3a94c8e1f198bf2da853a50cbe7dc3117ef4d2efb1549adae`.

## Immutable artifact index

All paths are relative to `backend/runtime/offertoday-research/`.

| Evidence | Run ID | Manifest SHA-256 |
|---|---|---|
| Repeat 1 baseline A | `cef97adb-ad94-4c94-9423-7b2f61fcf2fd` | `5a5e28567ad610e91ac51d648b48d9d3f6ff24deb4af182771eea06526062ec9` |
| Repeat 1 baseline B | `d48e8262-9122-491a-b868-5cf8dbb66baf` | `4da534b277fa22d1377e5e30578fd141958c9944a1d1989dc582f13298df1374` |
| Repeat 1 bake-off | `99876757-fce0-401f-adc8-e6fd3ae9aabc` | `87a954baa99c5a56fe9336c85f7e5350c950257c1b14069641891eebf76367bf` |
| Repeat 2 baseline C | `212b4cc6-b0d7-4f3f-8c64-aba4e8243dc9` | `2b32c978b49fa1fe43aa090947a25978451c0ebe6cfdfcc94c0a7bb8d71b5805` |
| Repeat 2 baseline D | `6f1817ca-f49c-4abc-b845-bdf37fbd6b6f` | `d36273e3fa315f14ded9502fe1a4c677fc22c432fa36509508754534c2ff89d5` |
| Repeat 2 bake-off | `d301b397-bf2c-4424-a20b-0935f675f9cb` | `b931a9abd8a96214b5061743d56f2ca176d76d79740629843460bf5080dbfb0f` |
| Comparison | `7a35b33e-580d-4aae-85d7-8a1ac9fb2b9b` | `845a356f8f0e518bbe91a95674d4a848699d4a1e193c4df96e6597cc509bc861` |
| Independent recomputation | `5f9d2ae3-4933-4e71-baf7-6ac541c13142` | `a564e3f452be26e253cd6f16abea123a1a2b206fa443e012f99248ca65892536` |

The four fresh baselines were distinct and matched on snapshot hash
`e7a8bfff5405d26fe5f363969283d8fee31fedbde21fa93b1affff13eed43dd1`
and inventory hash
`c234366c81098128d91d9680f9edd4292ad82ce0511bbed0ffd07d3536b7a43d`.

## Frozen execution and no-write evidence

Both repeats used seed `20260713`, all five frozen variants, all three frozen
categories, and the exact per-repeat budget.

| Repeat | Logical | Physical | Detail | Product writes | Stage calls | Would-stage rows | Snapshot/inventory/product hashes unchanged |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 150 | 150 | 0 | 0 | 0 | 0 | yes |
| 2 | 150 | 150 | 0 | 0 | 0 | 0 | yes |

Each repeat contained 15 complete executions, 150 page-attempt events, and no
transport retry. All 15 conditions ended as bounded `condition_incomplete`
because the frozen 10-page research cap was reached before cursor-confirmed
terminal plus empty confirmation.

## Repeat summaries

| Variant | Repeat 1 distinct / duplicate rate | Repeat 2 distinct / duplicate rate | Cursor violations | Gaps per repeat | Identity/conflict/conservation failures |
|---|---:|---:|---:|---:|---:|
| `stateless-current` | 179 / 40.33% | 177 / 41.00% | 0 | 3 | 0 |
| `ui-cursor` | 300 / 0% | 300 / 0% | 0 | 3 | 0 |
| `ui-cursor-50` | 300 / 0% | 300 / 0% | 0 | 3 | 0 |
| `ui-cursor-restart` | 300 / 0% | 300 / 0% | 0 | 3 | 0 |
| `ui-cursor-same-browser` | 300 / 0% | 300 / 0% | 0 | 3 | 0 |

The combined stateless control had 244 duplicate rows out of 600
(`40.6667%`) and a 206-ID union. Every cursor variant had zero duplicates, a
higher union, the same 60 logical-page cost, zero cursor/identity/conservation
failures, and no unclassified zero-new full page. Those passing properties do
not override the frozen gap and stability gates.

## Candidate comparison

| Variant | Two-repeat union | Duplicate reduction absolute / relative | Minimum condition Jaccard | Rejection reasons |
|---|---:|---:|---:|---|
| `ui-cursor` | 395 | 40.6667 pp / 100% | 0.324503 | `unresolved_gap`, `condition_jaccard` |
| `ui-cursor-50` | 340 | 40.6667 pp / 100% | 0.694915 | `unresolved_gap`, `condition_jaccard` |
| `ui-cursor-restart` | 383 | 40.6667 pp / 100% | 0.324503 | `unresolved_gap`, `condition_jaccard` |
| `ui-cursor-same-browser` | 376 | 40.6667 pp / 100% | 0.333333 | `unresolved_gap`, `condition_jaccard` |

Every candidate missed the frozen `>= 0.95` minimum same-condition Jaccard and
retained three unresolved page-cap gaps per repeat. Therefore no variant can be
frozen, `freeze-discovery-candidate` must not run, and no cursor-correct census
or Phase C live work is authorized from this evidence.

## Required stop

This is the explicit no-candidate decision required by implementation-plan
Task 8 and the task checklist. Runtime artifacts remain ignored and
uncommitted. A subsequent endpoint-contract investigation requires a new
bounded design amendment and separate authorization; this child does not
auto-start it.
