# Test design

## System boundary

The UI is the operator boundary, not the primary subject under test. Every
mutating scenario starts from the Automated Classification console. Network and
database observations are corroborating evidence only.

```text
UI action
  -> classification HTTP request/response
    -> persisted run and stable item snapshot
      -> domain adapter and optional LLM call
        -> current taxonomy/assignment/candidate mutations
          -> UI progress, failure detail, and terminal state
```

No direct SQL mutation, hand-crafted run row, or hidden API-only lifecycle action
may substitute for a UI action that the console exposes.

## Evidence model

Each scenario records:

1. domain, Source filter, requested limit, and browser action;
2. request payload, response status/body, and returned run ID;
3. before/after read-only database facts scoped to that run/candidate;
4. visible progress, failure reason, and terminal state;
5. expected contract, actual result, and pass/fail/blocked disposition.

Screenshots support a finding but do not replace request, run-ID, or persistence
evidence. API keys, prompts containing private data, and other secrets must not
be copied into reports or issues.

## Scenario ordering

Run read-only and smallest-mutating checks first so later assignments do not
invalidate earlier candidate counts.

1. Readiness and automated regression baseline.
2. Read-only preview/filter/limit checks for both retained domains.
3. One-to-three item real run for Company Industry, then Skills,
   with domain-specific before/after verification.
4. A combined concurrency scenario: keep one same-domain run active long enough
   to attempt a second same-domain start, start a different domain to prove
   independence, then immediately request Stop. The requested limit is at most
   20.
5. Inspect natural failures and exercise failed-only Retry if available.
6. Re-check terminal histories after reload/new browser context.

The combined scenario minimizes extra LLM consumption while testing active-run
conflict, cross-domain independence, polling, and cooperative Stop.

## Domain proof obligations

### Company Industry

- Candidate belonged to the requested Source and lacked a current assignment.
- Success is backed by a current Source mapping and preserved Job evidence.
- Missing/unsupported evidence fails the item without guessing a label.

### Skills

- Candidate was unresolved and met the effective threshold at selection time.
- Exact current name/code/alias matches are reused and affected Jobs are
  reprojected.
- Generic/suppressed candidates create no Skill.
- New Skill creation is atomic and uses an existing active
  Category/Technology path; uncertain placement leaves no partial/fallback
  mutation.

Which Skill branch occurs is determined by natural sandbox candidates. Branches
not encountered are checked against automated tests and marked as interactive
coverage limitations rather than manufactured with SQL.

## Defect policy

A failed expectation is filed only after it is reproduced or independently
corroborated by durable run/network/database evidence. Candidate-specific model
uncertainty and provider failures are not product defects unless the product
misclassifies, corrupts state, violates lifecycle rules, or presents the failure
incorrectly.

Each independent behavior defect receives its own GitHub issue linked to #32.
The issue is user-facing and durable: expected/actual behavior and reproduction
steps are required; implementation file paths are omitted.

## Safety and rollback

- Current data is sandbox data and may be classified.
- Ordinary runs start at one to three items.
- The sole concurrency/Stop run is capped at 20 and stopped immediately.
- Testing stops if the browser targets a non-local/non-sandbox deployment, if
  credentials are exposed, or if observed requests exceed the approved limits.
- There is no data rollback requirement; run IDs and mutations remain as QA
  evidence in the disposable sandbox.
