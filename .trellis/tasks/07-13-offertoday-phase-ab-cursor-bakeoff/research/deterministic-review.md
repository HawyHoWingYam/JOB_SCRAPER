# Phase A/B deterministic review checkpoint

## Scope and state

- Reviewed and refreshed on 2026-07-13 at `HEAD=507f85d5` on branch `codex/offertoday-it-coverage-20260702`.
- Implementation-plan Tasks 1-8 are complete through the deterministic review gate.
- The requirement-by-requirement evidence is recorded in
  `research/tasks-1-8-requirement-audit.md`.
- Pre-registered frozen Phase B order seed: `20260713`.
- Frozen per-repeat budget: 150 logical listing pages, 300 physical attempts, zero detail attempts, and zero product writes.
- No live request, browser launch, product write, staging mutation, production-default switch, commit, or push was performed.

## Frozen Phase B preflight inputs

### Variant controls

The endpoint is `/wapi/geek/recommend/search/list` and `rcdType` is omitted for every variant.

| Variant | Cursor | Requested page size | Browser lifecycle |
|---|---|---:|---|
| `stateless-current` | None | 50 | One shared runtime; research control only |
| `ui-cursor` | Response-derived | 10 | One runtime shared across the variant; cursor isolated per condition |
| `ui-cursor-50` | Response-derived | 50 | One runtime shared across the variant; cursor isolated per condition |
| `ui-cursor-restart` | Response-derived | 10 | Restart the browser between pages |
| `ui-cursor-same-browser` | Response-derived | 10 | One fresh runtime dedicated to one condition chain |

### Exact repeat order

The following order was computed offline with `build_bakeoff_order(repeat_index=<1|2>, order_seed=20260713)` before reading any Phase B response.

#### Repeat 1

| Sequence | Category | Category order | Variant |
|---:|---:|---:|---|
| 1 | 118000 | 1 | `ui-cursor-same-browser` |
| 2 | 118000 | 2 | `ui-cursor-restart` |
| 3 | 118000 | 3 | `stateless-current` |
| 4 | 118000 | 4 | `ui-cursor` |
| 5 | 118000 | 5 | `ui-cursor-50` |
| 6 | 112000 | 1 | `ui-cursor` |
| 7 | 112000 | 2 | `ui-cursor-same-browser` |
| 8 | 112000 | 3 | `stateless-current` |
| 9 | 112000 | 4 | `ui-cursor-50` |
| 10 | 112000 | 5 | `ui-cursor-restart` |
| 11 | 127000 | 1 | `ui-cursor` |
| 12 | 127000 | 2 | `stateless-current` |
| 13 | 127000 | 3 | `ui-cursor-same-browser` |
| 14 | 127000 | 4 | `ui-cursor-50` |
| 15 | 127000 | 5 | `ui-cursor-restart` |

#### Repeat 2

| Sequence | Category | Category order | Variant |
|---:|---:|---:|---|
| 1 | 118000 | 1 | `ui-cursor-same-browser` |
| 2 | 118000 | 2 | `ui-cursor-50` |
| 3 | 118000 | 3 | `stateless-current` |
| 4 | 118000 | 4 | `ui-cursor` |
| 5 | 118000 | 5 | `ui-cursor-restart` |
| 6 | 112000 | 1 | `ui-cursor-same-browser` |
| 7 | 112000 | 2 | `stateless-current` |
| 8 | 112000 | 3 | `ui-cursor-50` |
| 9 | 112000 | 4 | `ui-cursor` |
| 10 | 112000 | 5 | `ui-cursor-restart` |
| 11 | 127000 | 1 | `ui-cursor-same-browser` |
| 12 | 127000 | 2 | `ui-cursor-restart` |
| 13 | 127000 | 3 | `stateless-current` |
| 14 | 127000 | 4 | `ui-cursor-50` |
| 15 | 127000 | 5 | `ui-cursor` |

### Offline provenance summary

`capture_research_provenance()` completed offline with exit code 0. The raw patch and excluded path/hash maps were not copied into this checkpoint.

- Captured at: `2026-07-13T10:23:38.052222+00:00`.
- Commit SHA: `507f85d54b0e0fb6f04771dfdf292f0ac48c3e8a`.
- Canonical UTF-8 working-tree patch SHA-256: `c703f5e7252a29fda0d990023311e426165aa3a8992ae3e1fc5bb965c8be7b85`.
- Canonical UTF-8 working-tree patch size: `1430752` bytes.
- Included untracked file hash count: `17`.
- Excluded tracked file hash count: `4`.
- Excluded untracked file hash count: `380`.
- Runtime context: command `phase-b-preflight`, session mode `offline-no-browser`, crawl-job status `not_started`, order seed `20260713`.

#### Relevant source hashes

| Path | SHA-256 |
|---|---|
| `backend/app/repositories/offertoday_research_repository.py` | `f697dab9124eba68e9801ed8c92a658acced55d12399f881233b9f316162c689` |
| `backend/app/scraper/offertoday_browser_detail_scraper.py` | `608d209562e77d57095590a7070642b8df5cb013fa7d603d3550ecee05db4f7d` |
| `backend/app/scraper/offertoday_browser_runtime.py` | `d81b270781ff09d58676c9dc5634bc86d542266600193fd04bf34ba4fb401ad6` |
| `backend/app/services/crawl_job_runtime.py` | `0ec8fb49c18457f688035eee7c50ba48ea6b0fe5119f43b6926b0251eb1542ef` |
| `backend/app/services/offertoday_detail_pipeline.py` | `746e861361a7fa2f3d4a1d64c2a24ecdee726af1d8e7b9b92de79d672c659759` |
| `backend/app/services/offertoday_research_live_service.py` | `7f444116f68644b9a3ecf71c66d4f1b90b7ab64efb2a461254429984ac7e0575` |
| `backend/app/services/offertoday_research_staging_service.py` | `90b7a153219b19919d0af9b7df41fa603e32c21edb8f557e40655453949f6cf9` |
| `backend/app/sources/offertoday/__init__.py` | `63d0c907f9d9cd1c715b8962669bac0959c4d456160b979c944cc40f93d1517e` |
| `backend/app/sources/offertoday/completeness.py` | `0d182ea07de820a02a6fad2ba81188291041bc1a746a5c087ee00b2502d4d9ab` |
| `backend/app/sources/offertoday/constants.py` | `ad097045873ee08f7de5ef5bd317d08f39d60efd1cb8c558c82b86d27425324f` |
| `backend/app/sources/offertoday/detail_identity.py` | `48f6b96214d3315db08656d597a4a15572a86f11c50daf68393cdbeae72730c1` |
| `backend/app/sources/offertoday/listing_contract.py` | `dd0e7919a352ed7ca109fb28cd4cb3a8ee1e2ebefe48905fe2062cb56da4c28f` |
| `backend/app/sources/offertoday/listing_runner.py` | `b34af6792d21db902f2edd314deb80cb46f3e485bacea94b11161cbcae822839` |
| `backend/app/sources/offertoday/parsers.py` | `4db5018427ed1df30fc3a356acaa368cc8b1ec2439d6fc0398063121828a4001` |
| `backend/app/sources/offertoday/quality.py` | `c57ec09d652db25bec2fad95f655d398137fa29026dae10a93d982fe25ea00ed` |
| `backend/app/sources/offertoday/research/__init__.py` | `ef55fe7b71aa5fa6132883152e543a01e97f9c080d2f2acbaf4a49bd56217402` |
| `backend/app/sources/offertoday/research/artifacts.py` | `45fbcd9e80e4456ae659313558c20030e55cc50e7dda13e6f0a815d390b8e489` |
| `backend/app/sources/offertoday/research/baseline.py` | `3a065403a909d605c264fca64b4193f4b4460375d593d87b429e96fe53ac8534` |
| `backend/app/sources/offertoday/research/calibration.py` | `d87c785908b36887a16eafc7f1d84b62b4178a6f6a16eb487abe7235749e62f3` |
| `backend/app/sources/offertoday/research/conservation.py` | `4a77af8a6c5acfa6b23eff7c93a3ab34f556d634fd022eb7e102862bbd39e8a3` |
| `backend/app/sources/offertoday/research/contracts.py` | `741ee45c977288634e253cde189f9214a44efe441f65cc54b2566553ff01f242` |
| `backend/app/sources/offertoday/research/live_contracts.py` | `04ff5b45bd042f69c5ce54956e7f1e36190157e04ab611d6018bf970f2ec9d1a` |
| `backend/app/sources/offertoday/research/pagination_bakeoff.py` | `cbad52f9a85ac68b6e17e64319a8889676972d32158c170a751f11c6ad5c9f83` |
| `backend/app/sources/offertoday/research/pagination_stage_gate.py` | `d7f881b8953da9a7dcdc56cae44b9098e529fb6a9fbf4d05aa049d8df293d742` |
| `backend/app/sources/offertoday/research/smoke.py` | `5798cfab5f276789fd2f1483344b80ecc2b232d4bb9e85fb7eeab2f75089286d` |
| `backend/app/sources/offertoday/research/stability.py` | `ab8b0c22425ec5c2b7b6a48360debaf48e945c2f9dde3695bbf63565dd79298a` |
| `backend/app/sources/offertoday/research/stage_gate.py` | `e5e9cc32bcb94eacde50bd9fb39805129a32f9d9dfd6c2b932f34af1c84cbe95` |
| `backend/app/sources/offertoday/response_policy.py` | `54749cb263cd05a69b9ea0c9957cd17a47c0da0b3b2c295a54a5aac4e0f98b0c` |
| `backend/app/sources/offertoday/search_space.py` | `cc7d8c9d357ec4867ac83186bb69b5899cff64e998640e66f50d4af7088a42ce` |
| `backend/app/sources/offertoday/staging.py` | `1eb01dc5293cbfeee0b43815adaeead60c9e506641928e7c01b26076af396f15` |
| `backend/scripts/offertoday_coverage_audit.py` | `60021e95d791fb51f6b18a9e4ab01da83774b8347fe801ac4a953253ed2b0d0d` |
| `backend/scripts/offertoday_research.py` | `3ba505b46071523dafd68879d653b91e9fa065fb7bd8b08040da74c5c6870068` |
| `backend/scripts/offertoday_research_census.py` | `75c5b424e50ef0f48fa9fe594e91bb8412aaa89273704ebd05dc4fea8238a3db` |
| `backend/scripts/offertoday_standalone_crawl.py` | `74e9d6d82961b2382fbe6002b3fa835104da5c51a8e470d619c998f686235ab8` |

#### Compose hashes

| Path | SHA-256 |
|---|---|
| `docker-compose.yml` | `80730742a7083807cded7a6c67b8014583d560f87e32452b10f3c448b7061dcd` |
| `docker-compose.dev.yml` | `da3ef47f18126300c638432e65d25458f03fc071ddf8d79ab2e0851c93c34ec2` |

### Artifact root and infrastructure readiness

- Artifact root `C:\Work\JOB_SCRAPER\backend\runtime\offertoday-research` exists and is a directory.
- `git check-ignore -v` confirms both the root and its contents are ignored by `.gitignore:78` through `backend/runtime/`.
- `docker compose ps --format json` exited 0. All 11 long-running Compose services are running; seven report healthy and four workers have no configured health check.
- The healthy services include `backend-api`, `frontend-ui`, `postgres-db`, `redis-mq`, `scrapyd`, `recommendation-api`, and `retrieval-api`.
- The worktree has 76 top-level status entries. No unrelated entry was changed or staged by this preflight.
- Infrastructure readiness does not prove an authenticated OfferToday browser session, live endpoint reachability, or matching database baselines. Those checks remain inside the approval-gated Phase B sequence.

## Review findings resolved

- Failed and unexpected executions now export type-only, strict-replayable frozen prefixes, including shared-runtime close failures.
- Comparison requires four distinct baseline artifacts whose snapshot and inventory state match across repeats.
- Start/end snapshot, product-data, inventory, no-write, and staging evidence is independently replayed.
- Incomplete conditions count as unresolved gaps and cannot become candidates without terminal plus empty confirmation.
- Browser-restart zero-new replay is classified separately from an unclassified zero-new full page.
- Strict replay recomputes session continuity, effective page size, cursor classifications, nested row/cohort schemas, execution scalars, stop/gap state, budgets, and staging counts.
- Candidate selection rejects every individual gate, multiple passing variants, input-order drift, and no-candidate outcomes.
- `foundation-baseline` now has exact strict-verifier routing, so every baseline
  used as a live parent passes both generic verification and semantic replay.

## Verified commands

- Expanded Phase A/B focused suite: `954 passed, 16 warnings in 58.24s`.
- Complete backend suite: `1221 passed, 63 warnings in 62.17s`.
- Focused production-default guards: `3 passed`.
- Scoped Ruff: passed.
- Scoped `py_compile`: passed.
- `git diff --check`: passed; only existing LF-to-CRLF warnings were emitted.
- Plan 2 primary artifact index: `12/12` documented manifest hashes matched and `12/12` passed both generic and strict replay.

## Worktree note

- The repository remains intentionally dirty with unrelated user changes preserved.
- The new tests `test_offertoday_listing_contract.py`, `test_offertoday_pagination_bakeoff.py`, and `test_offertoday_pagination_stage_gate.py` are hidden by the existing `backend/tests/*` ignore rule and will require explicit force-add if a later commit is authorized.

## Gate outcome

The deterministic review passed and the user explicitly approved live Phase B.
Both repeats, four parent baselines, the comparison, and its independent
recomputation completed and passed generic plus strict verification. No variant
passed the frozen gap and Jaccard gates, so no discovery candidate was frozen.
The exact evidence and explicit no-candidate stop are recorded in
`research/phase-b-live-decision.md`. Phase C was not started.
