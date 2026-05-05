# AI Settings UI Refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the AI settings page easier to scan and edit by reducing duplicated status content and improving provider-selection and secret-entry UX.

**Architecture:** Keep the existing data model and API requests intact while restructuring the frontend page into a single-column editing flow. The work is isolated to the settings page component, its stylesheet, and the focused test file.

**Tech Stack:** React 19, Vite, Vitest, Testing Library, plain CSS, lucide-react

---

### Task 1: Lock the new interaction contract in tests

**Files:**
- Modify: `frontend/src/components/settings/AISettingsPage.test.jsx`

**Step 1: Write the failing test expectations**

- Replace dropdown-based provider assertions with provider-card assertions.
- Assert redundant runtime metadata labels are absent from the form.
- Add a show/hide API key toggle assertion.

**Step 2: Run test to verify it fails**

Run: `npm test -- src/components/settings/AISettingsPage.test.jsx`

Expected: existing settings tests fail because the page still renders dropdowns and duplicated runtime metadata.

### Task 2: Restructure the page component

**Files:**
- Modify: `frontend/src/components/settings/AISettingsPage.jsx`

**Step 1: Implement the minimal behavior**

- Add provider-card UI and metadata helpers.
- Add local API key visibility state.
- Remove profile runtime metadata blocks.
- Replace the empty top form panel with a compact action panel.

**Step 2: Run the focused test file**

Run: `npm test -- src/components/settings/AISettingsPage.test.jsx`

Expected: the updated tests pass.

### Task 3: Refresh the styles

**Files:**
- Modify: `frontend/src/components/settings/AISettingsPage.css`

**Step 1: Implement the layout and control styling**

- Switch the shell to a vertical stack.
- Add provider card, secret badge, and toggle styles.
- Remove styling that only supported the old runtime metadata grid.

**Step 2: Re-run the focused test file**

Run: `npm test -- src/components/settings/AISettingsPage.test.jsx`

Expected: tests remain green after the style-only changes.

### Task 4: Verify production readiness

**Files:**
- No source changes required

**Step 1: Run frontend build**

Run: `npm run build`

Expected: Vite build succeeds.

**Step 2: Optional follow-up**

- If visual polish still feels off after the structural cleanup, do a second pass on spacing and copy without changing the interaction model.
