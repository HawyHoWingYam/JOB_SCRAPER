# Diagnose AI enrichment run job 409 conflict

## Goal

Make an AI enrichment readiness rejection actionable without weakening the backend rule that prevents runs from starting before the Jobs AI profile is configured and tested.

## Background

- The operator reports that using **Run job** in AI enrichment causes the browser to log: `Failed to load resource: the server responded with a status of 409 (Conflict)`.
- The supplied screenshot confirms the AI Enrichment **Filtered Run** action displays only `Run request failed with 409`, while the same page reports `Active runs 0` and no persisted runs.
- The action posts to `/api/ai/runs`. The backend returns two classes of 409: an active-run conflict object, or a string detail from Jobs AI profile readiness validation.
- The live `GET /api/settings/ai` response confirms the Jobs profile has no configured provider: `configured_provider: null`, `is_ready: false`, and `degradation_reason: "Profile is not configured"`.
- The frontend has dedicated handling for `detail.code=active_run_exists`, but discards string-valued `detail`, reducing the actionable backend message `jobs profile is not configured` to the generic status-only message.

## Requirements

- Establish an agent-runnable feedback loop that exercises the actual run-job request and asserts the reported 409 conflict.
- Preserve the backend readiness gate: an enrichment run must not start without a configured and successfully tested Jobs AI profile.
- Surface the backend's safe profile-readiness detail in the AI Enrichment action error instead of a generic status-only message.
- When the conflict is caused by Jobs AI profile readiness, tell the operator to configure and successfully test the Jobs profile before retrying and provide a link to the existing `#settings` AI Settings view.
- Keep the existing active-run-specific error, including its run ID.
- Preserve unrelated uncommitted work in the repository.

## Acceptance Criteria

- [x] A deterministic frontend test reproduces a `/api/ai/runs` 409 with string detail `jobs profile is not configured` and observes the current generic-message defect before the fix.
- [x] The root cause is supported by live runtime-status and code-path evidence.
- [x] The frontend change does not alter successful run creation once the Jobs AI profile is configured and tested.
- [x] A missing or unready Jobs AI profile remains rejected and produces an actionable UI message using the safe backend detail.
- [x] The readiness message tells the operator to configure and successfully test the Jobs profile before retrying and includes a working link to `#settings`.
- [x] An active run remains rejected and produces the existing active-run message with its run ID.
- [x] Relevant automated tests pass and include regression coverage at the real failure seam when such a seam exists.

## Technical Notes

- The real frontend seam is `runPendingEnrichment` in `frontend/src/components/ai/AIEnrichmentPage.jsx`; it already parses the JSON response before replacing all non-active-run failures with a status-only error.
- Add focused component coverage in `frontend/src/components/ai/AIEnrichmentPage.test.jsx` for both the string-detail readiness 409 and the structured active-run 409.
- No backend behavior change is required: `POST /api/ai/runs` must continue returning 409 until `ensure_profile_runtime_ready("jobs")` succeeds.

## Out of Scope

- Redesigning the AI enrichment workflow beyond the confirmed 409 cause.
- Changing unrelated crawl, taxonomy, or enrichment behavior.
