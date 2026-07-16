# Design: Scraper pacing settings UI

## Information Architecture

Turn the current AI-only Settings page into a Settings shell. First-level section
navigation selects AI Runtime or Scraper Pacing without disrupting the existing
hash-based application navigation.

Scraper Pacing consists of an explanatory header, active-task warning/link, and
three equal source cards. On narrower screens cards stack while keeping field and
action ownership visually inside each source.

## Card State Model

Each source card separately stores:

- last server snapshot;
- editable form values;
- dirty derivation;
- save/reset pending action;
- field validation and request feedback.

After Save or Reset, rebuild both server snapshot and form state from the API
response. Do not copy the AI secret/provider state machinery into pacing cards.
Use the existing feedback and validation presentation conventions.

## Validation and Accessibility

Labels include seconds/count units and visible range help. Invalid fields are
linked to concise messages and the card feedback uses an accessible alert/status
role. Save is disabled only for invalid, unchanged, or pending state; active
tasks trigger warning copy but do not disable it.

## Direct Override

Resolve the selected source's server-owned summary for display near detail task
controls. The summary states that values are global and fixed when a task starts,
with a navigation link to Scraper Pacing.

## Testing

Extend Settings interaction tests for section navigation, independent cards,
dirty/save/reset, validation, API failures, and active warnings. Add Direct
Override UI coverage because its current tests mainly cover payload helpers.
