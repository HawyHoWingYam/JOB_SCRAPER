# Implementation plan

1. Capture populated board and wizard baseline with isolated request fixtures; retain evidence under research.
2. Improve wizard navigation, summary, scope validation, review, and receipts while preserving authority; add regression tests for changed workflows.
3. Improve board rows/actions/context and preserve lifecycle/deep-link behavior; adapt behavioral tests.
4. Run focused taskControl Vitest, scoped ESLint, production build, then frontend test suite and isolated Scheduler Playwright journeys.
5. Inspect before/after screenshots at target sizes, record limitations, update affected UI contracts, and report reviewable diff. Do not close issue without manual QA.

Commands: `npm test -- src/features/taskControl`, `npx eslint src/features/taskControl`, `npm run build`, `npm test`, and dedicated Scheduler Playwright config. Run from frontend. No TypeScript check exists in this JavaScript package.

Risks: route hydration can lose unsaved fields or refetch old Automation values; review return can retain stale tokens; successful actions must not become resubmittable; disabled actions must preserve backend capability decisions. Test each rather than relying on screenshots.
