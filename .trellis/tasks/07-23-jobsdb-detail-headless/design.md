# Technical design

## Launch-mode seam

`JobsDBBrowserDetailScraper._start_sync_runtime` remains the single launch seam. It should resolve the task/request `crawl_mode` once, derive `headless = (mode == "headless")`, and pass that value to `launch_persistent_context_with_fallback`. The existing `reuse_open_browser` branch remains before fresh launch and continues to attach over CDP.

The profile-recovery child owns the fresh profile path. This child must accept an injected path and must not reintroduce the shared profile as a hidden default for fresh resumes.

## Manual recovery exception

Normal headless fresh execution has no desktop/helper dependency. A supported challenge can still expose the existing explicit helper flow: the operator opens a separate headed verification browser, completes the challenge, and selects `reuse_open_browser`. The selected strategy is persisted in the resume context and is observable in recovery events.

## Error contract

Fresh launch errors are classified by the shared recovery contract, including profile scope and runtime mode. The old “close all Edge windows” text is removed from the normal headless path. Attach failures retain a precise “verification browser unavailable” message and offer Fresh Profile.

## Compatibility

Requests without a mode use the source’s existing resolved default. Parser, navigation, interstitial classification, cancellation, and context cleanup remain unchanged.
