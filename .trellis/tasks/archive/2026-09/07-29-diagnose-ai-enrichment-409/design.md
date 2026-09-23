# Technical design

## Boundary

The backend readiness gate remains authoritative. `POST /api/ai/runs` continues
to return HTTP 409 when the Jobs AI profile is missing or has not passed its
runtime test. The frontend owns translating the already-safe response detail
into an actionable operator message.

## Error mapping

`runPendingEnrichment` parses the JSON response once and maps conflicts in this
order:

1. Structured `detail.code == "active_run_exists"` keeps the current message
   and run ID.
2. String-valued `detail` from the readiness gate is displayed as the reason,
   followed by instructions to configure and successfully test the Jobs
   profile before retrying.
3. Other responses retain a bounded status-based fallback.

The readiness error renders a link to the existing `#settings` route. It does
not navigate automatically, retry the request, or weaken backend validation.

## Compatibility

Successful run creation and monitoring are unchanged. The mapping accepts the
current string detail without requiring a backend schema change. Unknown error
shapes remain bounded and do not expose response bodies.
