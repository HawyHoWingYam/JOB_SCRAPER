# Fix crawl task partial metrics display

## Goal

Make the Crawl Tasks UI report OfferToday listing-only runs truthfully: distinguish
discovered IDs from rows actually staged, expose bounded/partial completion, and
describe query progress as consumed work versus a maximum request budget.

## Background

For crawl job `4cee200d-9b1b-40ad-88da-8866bacd71a7`, the durable metrics and
database state show:

- `job_ids_collected=9707` and exactly `6969` `crawl_job_listings` rows;
- `2738` complete existing IDs skipped, so `9707 - 2738 = 6969` staged rows;
- `listing_partial=true`, with `107` capped and `45` naturally completed
  conditions out of `152` total conditions;
- `pages_processed=2615` against a maximum budget of `152 * 20 = 3040` page
  requests;
- all page attempts returned `classification=success` and `api_code=0`, with no
  WAF/IP-block evidence. Page-cap termination is therefore not itself a block.

The current task snapshot inflates `listings_staged` by taking the maximum of the
actual staged count and `job_ids_collected`. The UI also renders terminal partial
runs as plain `Completed` and presents the maximum request budget like an
ordinary page total.

## Requirements

- Preserve `job_ids_collected` as the distinct discovered-ID metric.
- Project `listings_staged` from actual staged evidence only; do not promote it
  to the discovered-ID count.
- Expose listing partiality and condition totals/cap counts through the crawl
  task API snapshot.
- Render a completed partial listing run distinctly from a fully completed run
  and show the capped-condition count as actionable context.
- Label OfferToday query progress so the denominator is clearly a maximum
  request budget, not a claim that every remaining query must execute.
- Do not classify page-cap completion as API/network/WAF blocking without
  explicit blocking evidence.
- Preserve existing behavior for non-OfferToday sources and non-partial runs.

### Authorized follow-up: OfferToday IP-block recovery

- Treat OfferToday `ip_blocked` as an explicit manual-action stop in both the
  listing/job-ID phase and the detail phase.
- Tell the operator to change the public IP or network before resuming; do not
  describe an IP block as a generic crawl failure.
- Persist a complete manual-action payload for resumable OfferToday session
  stops, including browser launch fields, resume capability, preferred
  strategy, instructions, classification/code, evidence, and resume context.
- Keep identity-audit stops non-resumable.
- Preserve recovery for already-persisted OfferToday session-recovery events
  that predate the complete payload contract.
- Make the host helper and Docker-side OfferToday CDP attach use the same host
  browser profile and configured CDP host.

## Acceptance Criteria

- [x] The affected job projects `IDs 9,707` and `Staged 6,969`, not two copies of
      `9,707`.
- [x] A completed run with `listing_partial=true` is visibly labelled partial
      and includes `107` capped conditions in its task-row context.
- [x] OfferToday query progress communicates `2,615` requests consumed out of a
      maximum budget of `3,040` without implying an interrupted network run.
- [x] A completed non-partial task retains the normal completed presentation.
- [x] Focused backend snapshot tests and frontend Crawl Tasks tests cover the
      corrected metrics and partial-state rendering.
- [x] Listing and detail `ip_blocked` stops expose a complete, resumable manual
      action with a clear change-IP instruction.
- [x] The existing legacy OfferToday task
      `21436eff-7d0f-4df2-9460-e4ab9d8805e2` can be opened and resumed after
      the host helper is running and the operator has changed IP.
- [x] Identity-audit manual actions remain non-resumable and do not expose
      browser-resume actions.
- [x] Focused backend/frontend tests cover new payloads, legacy normalization,
      IP-block rendering, and host CDP attachment.

## Out of Scope

- Changing OfferToday crawl depth, query families, page-cap policy, or retry
  behavior.
- Running the pending detail crawl for the inspected job.
- Treating `job_id` fallback as a proven detail-fetch failure; this listing-only
  run did not execute that validation.
