# OfferToday practical IT production crawl design

## Replacement Architecture

The production flow is:

```text
IT category + keyword + hybrid conditions
  -> search/pageSize=10/rcdType omitted
  -> condition-local response cursor
  -> validated resultList page
  -> bulk complete/terminal/new/repair classification
  -> immediate new/repair staging
  -> natural exhaustion or retained page-cap partial
  -> all conditions complete
  -> one deduplicated new/repair detail cohort
  -> existing detail pipeline
```

`suppleRcdList` remains a separate observation-only cohort.

## State Model

- Natural condition: two cursor-continuous empty result pages.
- Partial condition: page cap only; retain and continue.
- Hard stop: auth/WAF/IP, contract, identity, gap, or staging failure; stop the
  run and do not start detail.
- Successful run: every condition is natural or partial; final status
  `completed`, with `listing_partial` derived from capped conditions.

## Database Model

The current schema is sufficient:

- one bulk published-Job lookup per page;
- one bulk staging/blocker lookup;
- current-crawl uniqueness by canonical source ID;
- `detail_target_kind` stored in staging JSON as `new` or `repair`; and
- metrics stored in existing crawl-job JSON.

No migration is planned unless implementation demonstrates a concrete recovery
or query invariant that JSON cannot represent.

## Isolation Boundary

Move the production reconciliation sink out of the research-named service.
Keep the existing research packages, services, CLIs, strict replay, phase
tests, schemas, and local artifacts unchanged so historical runs remain
replayable. Production must not import or expand that research stack. Keep the
shared cursor, runner, response, identity, browser, staging, completeness, and
detail production primitives.

## Authoritative Detail

See Sections 4-9 of
`docs/specs/2026-07-14-offertoday-practical-it-production-crawler-spec.md`.
