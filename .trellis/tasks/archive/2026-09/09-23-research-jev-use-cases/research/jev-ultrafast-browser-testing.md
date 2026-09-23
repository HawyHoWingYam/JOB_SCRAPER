# Jev Ultrafast browser-testing assessment

## Source and reproducibility

- Repository: <https://github.com/browser-use/jev-ultrafast>
- Inspected revision: `1231850a0bf1a0c0341fe408ef1668dbbfdfac46`
- License: MIT
- A Python 3.12 `uv run --with` probe pinned to that revision built the package
  and imported `jev_ultrafast.Agent` successfully on 2026-09-23. This proves
  packaging compatibility only; it did not launch Chrome or make a paid call.

## What is reusable

The upstream agent observes visible page state and constructs a fresh indexed
action catalogue. Jev selects only a supported operation and a compatible target.
Code, not the model, owns DOM references and execution. Before acting, the
executor checks that the observation is current and that a target remains
connected, visible, enabled, in the viewport and not covered. Model output never
becomes a selector, coordinate, JavaScript program or shell command.

The design also separates text generation from action selection, caps steps,
records decisions and treats `DONE` as a proposal that still needs an independent
postcondition check. These are useful constraints for an optional Jev-guided
JOB_SCRAPER UI journey.

## Why the upstream Agent is not the release gate

The package is installable, but its current `model.py` posts System One requests
directly to `https://api.typesafe.ai/v1/systemone` using `TYPESAFE_API_KEY`.
JOB_SCRAPER supports a Settings-selected endpoint (including the user's
OpenRouter route), frozen settings, a cumulative budget ledger, reservations,
retries and persisted receipts. Direct upstream calls would bypass those controls
and create a second paid-call and audit path.

It also controls Chrome through `browser-harness` and CDP, whereas this project
already uses Playwright for deterministic frontend E2E. Replacing Playwright
would duplicate browser setup and weaken the existing fixture and request-audit
path. Upstream itself says a `DONE` choice is not proof of success and documents
shadow roots, frames, canvas, uploads, popup tabs, nested scrolling and arbitrary
widgets as current limitations.

Therefore:

1. Playwright remains the authoritative deterministic release gate.
2. An optional Jev-guided journey may choose from a code-produced, indexed set of
   visible Playwright actions.
3. Choices must go through JOB_SCRAPER's existing System One adapter, settings
   snapshot, budget ledger and receipts, not the upstream direct provider client.
4. The executor revalidates page/action freshness and supported targets before
   every action, enforces small step/cost limits and rejects arbitrary selectors,
   coordinates, script or shell output.
5. Deterministic Playwright assertions independently verify final database and
   UI state. A Jev `DONE` result never passes a test by itself.
6. Direct use can be reconsidered if upstream adds an injectable decision
   transport compatible with this project's budget and receipt boundary.

## Evidence limitations

Upstream performance figures are author-reported example results, not locally
reproduced JOB_SCRAPER measurements. This assessment made no paid call and makes
no browser reliability claim. The import probe does not validate Chrome setup,
provider credentials or application-specific postconditions.
