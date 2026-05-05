# AI Settings UI Refresh Design

> Last updated: 2026-05-04

## Summary

Refine the AI runtime settings page so operators can understand the page structure quickly and complete common edits without scanning repeated status blocks. The scope stays frontend-only and keeps the existing API contract unchanged.

## Problems Confirmed

- Profile sections repeat runtime state already shown in the summary cards.
- The page starts with a heavy hero and an almost-empty `Model Profiles` panel before users reach editable fields.
- Provider selection is hidden behind dropdowns, so switching providers takes extra clicks and gives no preview of what each option requires.
- API key state is technically correct but visually unclear because saved status, preview, and replacement input are split awkwardly.
- The two-profile editing flow is long, but tabs would hide the parallel relationship between the profiles and make comparison harder.

## Approved Direction

Use a single-column settings flow:

1. Keep a compact summary area at the top.
2. Add a small action panel with page guidance and the save button.
3. Stack the editable sections in this order:
   - `AI Enrichment`
   - `Companies`
   - `AI Enrichment Throughput`
4. Replace provider dropdowns with selectable cards.
5. Remove profile-level runtime metadata blocks from inside the form.
6. Improve API key presentation with:
   - saved badge
   - masked preview
   - show/hide toggle for newly entered values

## Deferred Ideas

- Profile tabs
- Copy settings between profiles
- Collapsible advanced settings

These are intentionally deferred to avoid adding more interaction layers before the base information architecture is fixed.

## Component Changes

### `AISettingsPage.jsx`

- Add provider card metadata and rendering helpers.
- Add local state for API key visibility per profile.
- Replace provider `<select>` controls with card buttons.
- Remove `configured provider / active provider / degraded state` blocks from `ProfileSection`.
- Replace the empty `Model Profiles` shell panel with a compact action panel.
- Keep throughput visible as a normal section, not an advanced accordion.

### `AISettingsPage.css`

- Convert the page form shell from a two-column layout to a stacked flow.
- Add provider card styles with clear selected state.
- Add field label rows, saved badge styles, and password toggle affordance.
- Tighten section spacing so cards and forms read as one system.

## Testing

- Update `frontend/src/components/settings/AISettingsPage.test.jsx` to assert the new provider-card flow.
- Verify redundant runtime metadata text is no longer rendered inside the form.
- Add coverage for the API key visibility toggle.
- Re-run the focused settings page test file and a frontend production build.
