# Implementation plan: Review OfferToday Job Detail keyword coverage

## 1. Lock the analysis contract

- [x] Re-read the task PRD/design and relevant OfferToday production-crawl and
      database specifications before editing.
- [x] Inspect the exact ORM models and existing inspector-script conventions.
- [x] Record the current PostgreSQL snapshot counts and catalog fingerprint as
      the report baseline.

## 2. Add a deterministic read-only analyzer

- [x] Create `backend/scripts/review_offertoday_job_detail_keywords.py` with a
      small `corpus` / `probe` / `report` CLI supporting Markdown and JSON
      output, explicit candidate input, minimum support, example limits, and
      hard live-probe budgets.
- [x] Separate database extraction, pure matching/recommendation logic, and
      rendering into independently testable functions.
- [x] Enforce PostgreSQL `SET TRANSACTION READ ONLY`, bounded statement time,
      rollback-on-success, rollback-on-error, and guaranteed session closure.
- [x] Load Source Classification Paths and all Keyword Entries without treating
      null execution evidence as zero contribution.
- [x] Implement exact production catalog normalization plus explicit Latin and
      CJK corpus-matching rules.

## 3. Curate and measure candidate terms

- [x] Add the task-local candidate CSV with the initial English/product/domain
      and Chinese title-variant families discovered during read-only profiling.
- [x] Run the analyzer against the current database and inspect every candidate
      meeting the support threshold using representative Job IDs, titles,
      classifications, dates, and bounded snippets.
- [x] Reject or defer candidates that are broad, benefit/location noise,
      duplicate an existing semantic family, or are unsupported by multiple
      distinct relevant Jobs.
- [x] Account for all 127 current Information Technology terms; label low/zero
      corpus matches as needing execution evidence, never automatic removal.

## 4. Produce the review report

- [x] If corpus coverage is insufficient or retirement candidates remain,
      execute the bounded no-write probe with no more than 30 add candidates,
      30 retirement candidates, two pages per target, and 250 listing API
      requests overall.
- [x] Repeat only zero/negligible-contribution retirement candidates in an
      independent one-page pass within the same 250-request total cap; downgrade
      any partial/hard-stopped result to needing more evidence.
- [x] Save sanitized target/page/identity/overlap evidence to
      `research/live-probe.json` and confirm no secret-bearing request or raw
      response data is present.

- [x] Generate `review-report.md` with the exact database population, date and
      language skew, missing query-provenance warning, classification
      distribution, candidate evidence, and per-pack conclusions.
- [x] Clearly distinguish corpus discovery support from actual query recall,
      precision, or incremental contribution.
- [x] Include an exact regeneration command and the effective thresholds.
- [x] Confirm that the report recommends no direct catalog mutation and routes
      any accepted future change through CSV preview/confirm.

## 5. Test and verify

- [x] Add `backend/tests/test_review_offertoday_job_detail_keywords.py` for
      normalization, matching boundaries, multi-path membership, distinct-job
      counts, thresholds, null evidence, deterministic rendering, and the
      read-only transaction guard.
- [x] Add scripted probe coverage for request/page/target caps, pacing,
      cursor isolation, second-pass retirement fencing, hard-stop handling,
      sanitized evidence, and zero persistence calls.
- [x] Run:

      ```bash
      python3 -m pytest -q backend/tests/test_review_offertoday_job_detail_keywords.py
      ruff check backend/scripts/review_offertoday_job_detail_keywords.py backend/tests/test_review_offertoday_job_detail_keywords.py
      python3 backend/scripts/review_offertoday_job_detail_keywords.py \
        corpus \
        --candidate-file .trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/candidate-terms.csv \
        --output .trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/corpus-snapshot.json
      python3 backend/scripts/review_offertoday_job_detail_keywords.py \
        probe \
        --corpus .trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/corpus-snapshot.json \
        --output .trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/live-probe.json \
        --max-additions 30 --max-retirements 30 --first-pass-pages 2 \
        --second-pass-pages 1 --request-cap 250
      python3 backend/scripts/review_offertoday_job_detail_keywords.py \
        report \
        --corpus .trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/corpus-snapshot.json \
        --probe .trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/live-probe.json \
        --output .trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/review-report.md
      python3 backend/scripts/review_offertoday_job_detail_keywords.py report \
        --corpus .trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/corpus-snapshot.json \
        --probe .trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/live-probe.json \
        --format json --output /tmp/offertoday-keyword-review-1.json
      python3 backend/scripts/review_offertoday_job_detail_keywords.py report \
        --corpus .trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/corpus-snapshot.json \
        --probe .trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/live-probe.json \
        --format json --output /tmp/offertoday-keyword-review-2.json
      diff -u /tmp/offertoday-keyword-review-1.json /tmp/offertoday-keyword-review-2.json
      git diff --check
      ```

- [x] Audit the task diff and database before/after counts to confirm that the
      analyzer performed no INSERT, UPDATE, DELETE, DDL, or Keyword Pack change.

## Risk and rollback points

- Stop if the analyzer cannot enforce a read-only PostgreSQL transaction.
- Stop if Job classification membership cannot be derived without label-based
  inference.
- Treat snapshot/date skew or missing query provenance as report limitations,
  not reasons to manufacture precision or recall metrics.
- Rollback is file-only: remove the new analyzer, tests, candidate input, and
  generated report. No database rollback should be necessary because the task
  performs no writes.
