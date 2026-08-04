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
| Report input is unchanged | Produce deterministic JSON and ordered Markdown |

### 5. Good / Base / Bad Cases

- **Good:** a Chinese IT title phrase has repeated retained examples and adds
  distinct bounded-probe IDs beyond the current pack; report it with overlap
  risk and leave the catalog unchanged.
- **Base:** current coverage is sufficient; produce a no-change verdict without
  running an unnecessary mutation workflow.
- **Bad:** disable a zero-corpus term without query-contribution evidence, or
  present a two-page probe as complete OfferToday inventory coverage.

### 6. Tests Required

- Unit tests cover Unicode normalization, Latin boundaries, CJK matching,
  distinct-Job counts, multi-path evidence, thresholds, and deterministic
  rendering.
- Probe tests cover page/request/target caps, pacing, cursor isolation, second
  retirement pass fencing, hard stops, sanitized evidence, and zero persistence
  calls.
- A database seam verifies PostgreSQL read-only setup, rollback, and closure.
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
