# Technical design

## Boundary

This is a Board acknowledgement, not a crawl lifecycle transition. The crawl
job remains authoritative and unchanged; a dedicated append-only dismissal
event records that the operator no longer wants one exact terminal failure
projected as attention.

## Contracts

- Add `dismiss_failed_run` to the Board action contract.
- Add the targeted failure event sequence to failed attention items as an
  explicit revision token; clients must not parse `item_id` to recover it.
- Add a crawl-task mutation endpoint accepting that expected sequence.
- Record a source-neutral dismissal event containing the target failure
  sequence and `local-operator` actor.

The endpoint locks the crawl job, resolves the latest terminal failure event,
and then:

1. rejects any non-`failed` current job;
2. returns success when the same target already has a dismissal event;
3. rejects a sequence that is not the current terminal failure;
4. appends exactly one dismissal event otherwise.

## Projection flow

The Board loads current failure and dismissal events in a dedicated lookup.
`failed_run` is suppressed only when the current `crawl.failed` sequence has a
matching dismissal. Task snapshot/status projection must continue to use the
failure lifecycle event rather than treating the Board-only dismissal as a new
lifecycle outcome.

Data flow:

```text
failed Board item + failure sequence
  -> POST dismiss mutation
  -> row lock + current-failure comparison
  -> append dismissal event
  -> Board refresh
  -> suppress matching failed attention only
```

## Frontend behavior

The existing Board action dispatcher calls the new API immediately. It uses
the existing mutation busy/error state and reloads the Board on success. No
dialog, optimistic-only hiding, undo state, or Task Details action is added.

## Compatibility and safety

- The new action and failed-event revision field are additive Board V2 fields.
- Older clients ignore the extra action/field.
- No database migration is required because the existing append-only crawl
  event store owns persistence.
- The dismissal event is not a lifecycle/status event and must not replace the
  current failure when building task snapshots.
- A future failure has a different sequence and therefore cannot inherit an old
  dismissal.

## Rollback

Removing the action/endpoint and suppression logic makes all historical failed
runs visible again; crawl state is unchanged. Dismissal events can remain as
inert audit history.
