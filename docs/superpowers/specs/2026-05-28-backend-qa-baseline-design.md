# Backend QA Baseline Dual-Path Design

> Date: 2026-05-28
> Scope: Iteration A of the project audit and optimization cycle
> Priority order: A (stability / QA baseline) -> C (frontend UX / observability) -> B (runtime crawl success)

## Goal

Normalize backend verification so both of these paths are officially supported and demonstrably usable:

1. Host-side local execution
2. Docker-based execution through the existing `docker compose` stack

The result must remove hidden import-path assumptions, document the supported commands, and make regression verification predictable before later work on scheduler UX or crawler runtime behavior.

## Current Evidence

The current repo state shows:

- Frontend baseline is already green:
  - `npm test` passes
  - `npm run build` passes
- Targeted backend Docker tests already pass for the recent CTGoodJobs and crawl-worker changes.
- Full backend pytest collection is blocked by an import-path inconsistency in `backend/tests/test_bootstrap_db.py`.
- `backend/tests/conftest.py` currently inserts the `backend/` directory onto `sys.path`, which supports `app.*` imports but does not guarantee `backend.*` imports across host and container execution contexts.

This means the repo has a real QA baseline gap rather than a pure runtime bug.

## Problem Statement

The backend test suite is currently relying on mixed module-addressing models:

- one model treats `backend/` as the import root and imports modules as `app.*`
- another model tries to import through `backend.*`

Those models are not interchangeable across:

- running from the repo root
- running from inside the `backend/` directory
- running inside the Docker image where `/app` is the effective project root for backend code

As long as the suite mixes those assumptions, test collection can fail before meaningful regressions are even evaluated.

## Chosen Approach

Use the "dual-path normalization" approach.

This iteration will:

- standardize backend test imports around a single backend import boundary
- remove or correct tests that depend on `backend.*` resolution where that path is not actually the supported runtime model
- define one official host verification path
- define one official Docker verification path
- document both paths in the repo so contributors do not have to infer the correct working directory or environment assumptions

This iteration will not add a wrapper CLI or generalized CI abstraction layer yet. The first requirement is to make the underlying execution model coherent.

## Design Decisions

### 1. Single Backend Import Boundary

Backend tests will use import paths that are valid when the backend code directory is treated as the Python import root.

Practical implication:

- prefer imports that match the current backend runtime model such as `app.*`
- avoid `backend.*` imports inside tests unless the repo is deliberately converted into a package model that supports them everywhere

This is the smallest coherent change because the existing backend runtime already launches modules such as `python -m app.main`.

### 2. Explicit Host Verification Contract

Host verification is supported, but only after backend development dependencies are installed.

The host path will be documented as:

- install `backend/requirements-dev.txt`
- run backend tests from a documented working directory with a documented command

Host success does not mean "works in a bare Python installation with no dev dependencies." It means "works in a prepared local developer environment."

### 3. Explicit Docker Verification Contract

Docker verification remains the closest match to the shared execution environment.

The Docker path will use the existing compose services and run pytest through the backend container image. That path must verify that:

- test collection succeeds
- the previous `ModuleNotFoundError: No module named 'backend'` failure no longer occurs
- the documented command can be repeated without requiring users to guess path semantics

### 4. Documentation as Part of the Fix

The QA baseline is not complete if the code works but the workflow remains tribal knowledge.

This iteration therefore includes repo documentation updates that clearly state:

- the supported host verification command
- the supported Docker verification command
- which path is preferred when validating behavior closest to the containerized runtime

## Out of Scope

This iteration does not include:

- frontend UX changes
- scheduler or progress panel redesign
- crawler runtime logic changes
- CTGoodJobs proxy strategy changes
- new test wrapper scripts
- broad backend refactors unrelated to test execution consistency

Those belong to later iterations unless they become strictly necessary to complete the QA baseline.

## Error Handling Strategy

The work will distinguish between three failure classes:

### Import-boundary failures

These indicate a code or test-structure problem and should be fixed in code.

Example:

- importing `backend.scripts.bootstrap_db` in a context where only the backend source root is on `sys.path`

### Missing-dependency failures

These indicate a host environment setup issue, not a product bug.

The fix is:

- document required installation steps
- keep the test commands explicit

### Host-vs-Docker inconsistency failures

These indicate the supported verification paths are semantically different.

The fix is to align the import and execution assumptions instead of adding local one-off workarounds.

## Verification Plan

Implementation for this design is only considered complete when evidence shows all of the following:

1. Backend pytest collection no longer fails because of `test_bootstrap_db.py` import resolution.
2. A documented host command can run backend tests in a prepared local environment.
3. A documented Docker command can run backend tests in the backend container environment.
4. The commands and environment assumptions are written in repo documentation.

Preferred evidence set:

- host test command output
- Docker test command output
- updated documentation file content

## Deliverables

This design is expected to produce:

- corrected backend test import/path behavior
- a documented host-side backend verification workflow
- a documented Docker-based backend verification workflow
- an implementation report showing which commands were run and what results were observed

## Risks and Tradeoffs

- The host path may require a small amount of environment setup that some contributors do not currently have. That is acceptable as long as the requirement is explicit and reproducible.
- Docker and host may still differ in speed or dependency isolation. That is acceptable. What is not acceptable is having different import semantics or undocumented invocation rules.
- Avoiding a wrapper script in this iteration keeps the change smaller, but it means users will still run raw commands. That tradeoff is intentional until the baseline itself is stable.

## Success Criteria

This iteration is successful when backend verification is no longer blocked by path ambiguity and contributors have two clear, working ways to validate backend changes before moving on to the next priorities:

- C: frontend UX / operational visibility
- B: runtime crawl success and resilience
