# Companies Web Search Test Warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate web-search probe to the `Companies` profile test flow and surface its result as a warning or success detail without changing runtime readiness gating.

**Architecture:** Extend the backend AI settings probe API to report `model_check` and `web_search_check` independently for `companies`, then update the settings UI to render the richer result. Keep persisted runtime test pass/fail behavior anchored to the model check so existing readiness semantics stay intact.

**Tech Stack:** FastAPI, Python, React, Vitest

---

### Task 1: Backend Probe Contract

**Files:**
- Modify: `backend/app/api/settings.py`
- Test: `backend/tests/test_settings_api.py`

- [ ] **Step 1: Write the failing test**

Add API tests that assert `POST /api/v1/settings/ai/test` returns `web_search_check` for `scope=companies`, including unsupported and supported provider cases.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_settings_api.py -q`
Expected: FAIL because the endpoint does not yet return the new payload.

- [ ] **Step 3: Write minimal implementation**

Split the probe into a primary model check and an optional companies web-search check. Keep HTTP 200 when the model probe passes, even if web search is unsupported or fails.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_settings_api.py -q`
Expected: PASS

### Task 2: Frontend Feedback Rendering

**Files:**
- Modify: `frontend/src/components/settings/AISettingsPage.jsx`
- Test: `frontend/src/components/settings/AISettingsPage.test.jsx`

- [ ] **Step 1: Write the failing test**

Add UI tests that assert `Test Companies configuration` shows a web-search unsupported warning and a web-search success detail from the richer backend response.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test -- AISettingsPage.test.jsx`
Expected: FAIL because the UI only renders the legacy generic success message.

- [ ] **Step 3: Write minimal implementation**

Render model success plus web-search detail lines for `companies`, while keeping non-200 responses as the only error path.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test -- AISettingsPage.test.jsx`
Expected: PASS

### Task 3: Regression Verification

**Files:**
- Modify: `backend/app/api/settings.py` if needed
- Modify: `frontend/src/components/settings/AISettingsPage.jsx` if needed

- [ ] **Step 1: Run focused backend and frontend verification**

Run: `python -m pytest backend/tests/test_settings_api.py -q`
Expected: PASS

Run: `npm --prefix frontend test -- AISettingsPage.test.jsx`
Expected: PASS

- [ ] **Step 2: Run combined verification**

Run: `python -m pytest backend/tests/test_settings_api.py -q && npm --prefix frontend test -- AISettingsPage.test.jsx`
Expected: both commands pass
