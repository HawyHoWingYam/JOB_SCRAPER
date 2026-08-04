# OfferToday Keyword Coverage Review Contracts

## Scenario: review a Source Classification Keyword Pack

### 1. Scope / Trigger

Use this contract when reviewing whether an OfferToday Keyword Pack still
covers the retained Job Detail corpus or when validating proposed additions and
retirements. Review work produces evidence and recommendations; it does not
mutate Keyword Entries, Jobs, staging rows, or crawl configuration.

### 2. Signatures

```text
python backend/scripts/review_offertoday_job_detail_keywords.py corpus \
  --candidate-file <candidate-terms.csv> --output <corpus-snapshot.json>

python backend/scripts/review_offertoday_job_detail_keywords.py probe \
  --corpus <corpus-snapshot.json> --output <live-probe.json> \
  --max-additions 30 --max-retirements 30 \
  --first-pass-pages 2 --second-pass-pages 1 --request-cap 250

python backend/scripts/review_offertoday_job_detail_keywords.py report \
  --corpus <corpus-snapshot.json> [--probe <live-probe.json>] \
  --output <review.md|review.json> [--format markdown|json]

python backend/scripts/review_offertoday_job_detail_keywords.py cross-source-corpus \
  --candidate-file <cross-source-candidates.csv> \
  --baseline-corpus <archived-offertoday-corpus.json> \
  --output <cross-source-snapshot.json>

python backend/scripts/review_offertoday_job_detail_keywords.py cross-source-probe \
  --corpus <cross-source-snapshot.json> \
  --baseline-probe <archived-offertoday-probe.json> \
  --output <cross-source-live-probe.json> \
  --max-additions 30 --pages-per-candidate 2 --request-cap 60

python backend/scripts/review_offertoday_job_detail_keywords.py cross-source-report \
  --corpus <cross-source-snapshot.json> \
  [--probe <cross-source-live-probe.json>] \
  --output <review.md|review.json> [--format markdown|json]
```

### 3. Contracts

- `corpus` requires PostgreSQL, starts its transaction with
  `SET TRANSACTION READ ONLY`, applies a local statement timeout, and always
  rolls back and closes the session.
- Source Classification membership comes from Source-qualified path nodes, not
  mutable labels or the nullable legacy scalar Job field.
- Latin matching uses Unicode normalization, case folding, and alphanumeric
  boundaries. CJK phrases use normalized contiguous matching.
- A candidate needs at least three distinct relevant Job Details and two title
  examples before live confirmation. Corpus matches are discovery evidence,
  not query recall or precision.
- `probe` creates no database session. It stages evidence in memory, uses the
  production OfferToday response/cursor/identity contracts, and writes only a
  sanitized local artifact.
- The probe stops before exceeding 250 listing API requests and stops
  immediately on auth, WAF, IP block, cursor/session, or identity-integrity
  failures.
- Retirement requires corpus review plus zero/negligible contribution in a
  second independent bounded pass. Corpus absence alone never justifies it.
- Reports include counts, representative Jobs, recall benefit, precision/noise
  risk, limitations, and a per-pack verdict. Applying accepted changes remains
  a separate CSV preview/confirm operation.
- Cross-source discovery includes only non-deleted Jobs with nonblank title and
  description under the exact root path node `jobsdb:6281` or
  `ctgoodjobs:021`. The root node has `source_position=0`; display labels and
  nullable legacy scalar classification fields are never membership authority.
- JobsDB and CTGoodJobs counts may qualify a term for OfferToday probing but
  cannot themselves justify an OfferToday addition or retirement. A newly
  supported addition requires OfferToday-owned canonical IDs beyond the
  archived native/current-pack bounded samples.
- `cross-source-corpus` refuses an OfferToday population or Keyword catalog
  that differs from its archived baseline. It produces a deterministic bounded
  vocabulary inventory plus curated per-source candidate evidence.
- `cross-source-probe` accepts at most 30 candidates, two pages per candidate,
  and 60 listing API requests. It requires a complete archived baseline probe,
  creates no database session, and preserves the same hard-stop and sanitized
  evidence contracts as `probe`.
- An observed OfferToday row without a canonical identity is not contribution
  evidence. Report its observed-row count and downgrade the term to needing
  OfferToday evidence.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Database dialect is not PostgreSQL | Refuse corpus extraction before analysis |
| Read-only transaction cannot be established | Stop; emit no snapshot |
| Candidate has fewer than three details or two titles | Mark insufficient support |
| Probe would exceed its request/page/target cap | Refuse the next request or plan |
| Auth/WAF/IP/cursor/session/identity signal appears | Hard stop; issue no later request |
| Probe is partial or hard-stopped | Downgrade unsupported changes to needing evidence |
| Current term is absent only from the corpus | Do not recommend retirement |
| Cross-source Job lacks the exact source-qualified IT root | Exclude it; do not infer membership from title or label |
| Archived OfferToday corpus/catalog differs from current read-only snapshot | Stop the cross-source review |
| Cross-source probe requests more than 30 candidates, two pages, or 60 requests | Refuse before opening the runtime |
| Archived baseline probe is missing, partial, or stopped | Refuse before a fresh request |
| Fresh target has observed rows but zero canonical IDs | Mark `needs_offertoday_evidence` |
| Report input is unchanged | Produce deterministic JSON and ordered Markdown |

### 5. Good / Base / Bad Cases

- **Good:** a Chinese IT title phrase has repeated retained examples and adds
  distinct bounded-probe IDs beyond the current pack; report it with overlap
  risk and leave the catalog unchanged.
- **Base:** current coverage is sufficient; produce a no-change verdict without
  running an unnecessary mutation workflow.
- **Good:** a term repeats in both external IT corpora, has title examples, and
  contributes canonical OfferToday IDs beyond the archived current-pack sample;
  report it as a supported addition with its overlap/noise risk.
- **Base:** a tool appears hundreds of times only in descriptions. Preserve its
  counts but do not spend probe requests until it has two relevant title Jobs.
- **Bad:** disable a zero-corpus term without query-contribution evidence, or
  present a two-page probe as complete OfferToday inventory coverage.
- **Bad:** use the shared label “Information Technology” to mix roots across
  sources, or treat a JobsDB/CTGoodJobs match as OfferToday query contribution.

### 6. Tests Required

- Unit tests cover Unicode normalization, Latin boundaries, CJK matching,
  distinct-Job counts, multi-path evidence, thresholds, and deterministic
  rendering.
- Probe tests cover page/request/target caps, pacing, cursor isolation, second
  retirement pass fencing, hard stops, sanitized evidence, and zero persistence
  calls.
- A database seam verifies PostgreSQL read-only setup, rollback, and closure.
- Cross-source tests cover exact-root inclusion/exclusion, per-source distinct
  counts, baseline catalog fencing, candidate dispositions, deterministic
  vocabulary/report ordering, and the 30-candidate/two-page/60-request limits.
- Run focused review and listing-runtime tests, Ruff, `compileall`, deterministic
  report comparison, artifact secret scanning, catalog snapshot comparison, and
  `git diff --check`.

### 7. Wrong vs Correct

```python
# Wrong: corpus absence is treated as proof that a live query is useless.
if corpus_matches == 0:
    disable_keyword(keyword)

# Correct: preserve the catalog and require independent bounded contribution evidence.
decision = "needs_execution_evidence"
if corpus_reviewed and first_unique == 0 and second_unique == 0:
    decision = "retire_candidate"
```

```python
# Wrong: a shared display label becomes cross-source membership authority.
if classification.label == "Information Technology":
    include(job)

# Correct: require the owning Source's exact root path identity.
if root_node.source_classification_id in {"jobsdb:6281", "ctgoodjobs:021"}:
    include(job)
```
