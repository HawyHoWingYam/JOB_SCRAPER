# Verification

## Runtime cutover

- Existing schema upgraded idempotently with explicit embedding provenance.
- Existing 21,706 embedding rows were initially marked `legacy`.
- Description-only rebuild completed:
  - inspected: 21,706
  - rebuilt: 21,605
  - skipped as already current from canaries: 101
  - final `job-description-v1`: 21,706
  - missing retained Jobs: 0
  - legacy rows: 0
- `ix_jobs_description_trgm` exists in the sandbox. `EXPLAIN (ANALYZE,
  BUFFERS)` used it for `%python backend%` and completed in 43.751ms.
- A trial HNSW cosine index was removed after its plan returned only 61 rows
  for `LIMIT 1000` under the filtered current-contract query. The exact bounded
  vector path was retained because it returned the complete 1,000-row ranked
  window with a 470.854ms warm median.
- `backend-api`, `retrieval-api`, and `embedding-worker` were restarted on the
  current code. Database server default for omitted provenance is `legacy`.

## Live behavior

- A quoted Company-only value, `"Blockchain Solutions Limited"`, exists as a
  Company name but not in Description and returned zero lexical Jobs.
- `responsibilities`, present in Description, returned 13,738 lexical Jobs.
- `python backend` returned bounded semantic/hybrid responses with
  `result_kind=ranked`, `result_limit=1000`, and candidate counts of 1,000 /
  2,000 respectively.
- Representative top results included Python Developer roles; Hybrid completed
  below the 30-second public caller timeout.

## Benchmark

Command used the container runtime, three warm samples, one first-request
sample, and explicit budgets (Lexical Jobs 5s; Semantic/Hybrid Jobs 10s;
Facets 10s). It exited zero with no budget misses.

| Mode | First Jobs request | Warm Jobs median | Warm Facets median | Result contract |
|---|---:|---:|---:|---|
| Lexical | 69.141ms | 58.736ms | 454.340ms | exhaustive, total 534 |
| Semantic | 523.972ms | 561.444ms | 456.180ms | ranked 1,000 / candidate 1,000 |
| Hybrid | 1,712.600ms | 1,365.154ms | 377.215ms | ranked 1,000 / candidate 2,000 |

This final run happened after the process-level model had already initialized;
an earlier true process-cold Semantic request measured 13,294.328ms. The final
run also happened after dropping the trial HNSW index, proving that the exact
bounded path stays well inside the 10-second retrieval budget.

## Automated checks

- Frontend Job Browser component tests: 23 passed.
- Full frontend Vitest suite: 286 passed across 38 files.
- Frontend usability E2E: 7 passed.
- Frontend ESLint: passed.
- Frontend production build: passed.
- Final targeted backend search/embedding tests: 30 passed.
- Broader relevant backend group: 30 passed, 1 skipped.
- Full backend suite: 704 passed, 71 skipped, 1 unrelated pre-existing failure:
  `test_jev_runtime_is_excluded_and_cleared_by_disposable_cutover` asserts an
  existing Jev table-list relationship unrelated to Job Browser search.
- Black and Ruff on all touched Python files: passed after formatting.
- Mypy remains red with 1,154 repository-wide pre-existing ORM/stub errors;
  output includes existing errors in `jobs.py` and one missing optional
  `sentence_transformers` stub, not a clean project type-check baseline.
- Trellis task validation and `git diff --check`: passed.
