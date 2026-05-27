# Backend QA Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make backend verification work reliably on both host and Docker by normalizing the backend test import contract, documenting the supported commands, and proving both paths with live pytest runs.

**Architecture:** Keep the `backend/` directory as the Python import root for backend tests and runtime code. Fix the lone `backend.*` import regression, document one repo-root host verification path plus one container verification path, and verify both with collection and execution commands instead of adding wrapper scripts.

**Tech Stack:** Python 3.11, pytest, FastAPI backend package layout (`app`, `scripts`), Docker Compose

---

## File Map

- `backend/tests/test_bootstrap_db.py`
  - Regression test for `bootstrap_database()` and the schedule default SQL update.
  - Must import backend code through the same source-root model used by runtime modules.
- `backend/tests/conftest.py`
  - Shared pytest bootstrap file.
  - Documents the intended backend import contract for the whole test suite.
- `README.md`
  - Canonical contributor-facing commands for host and Docker backend verification.

### Task 1: Normalize the bootstrap-db regression test import boundary

**Files:**
- Create or update: `backend/tests/test_bootstrap_db.py`
- Test: `backend/tests/test_bootstrap_db.py`

- [ ] **Step 1: Use the current Docker collection failure as the red signal**

Run:

```bash
docker compose run --rm backend-api python -m pytest -q tests/test_bootstrap_db.py
```

Expected:

```text
ERROR collecting tests/test_bootstrap_db.py
ModuleNotFoundError: No module named 'backend'
```

- [ ] **Step 2: Rewrite the regression test to import through the backend runtime source root**

Replace `backend/tests/test_bootstrap_db.py` with:

```python
from __future__ import annotations

from scripts.bootstrap_db import bootstrap_database


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, statement) -> None:
        self.executed.append(str(statement))


class _FakeBeginContext:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _FakeConnection:
        return self.connection

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def begin(self) -> _FakeBeginContext:
        return _FakeBeginContext(self.connection)


class _FakeMetadata:
    def __init__(self) -> None:
        self.bind = None

    def create_all(self, *, bind) -> None:
        self.bind = bind


def test_bootstrap_database_backfills_ctgoodjobs_schedule_defaults_to_headless():
    connection = _FakeConnection()
    engine = _FakeEngine(connection)
    metadata = _FakeMetadata()

    bootstrap_database(db_engine=engine, metadata=metadata)

    crawl_mode_updates = [
        statement
        for statement in connection.executed
        if "UPDATE scrape_schedules" in statement and "SET crawl_mode = CASE" in statement
    ]
    assert len(crawl_mode_updates) == 1
    assert " = 'jobsdb' THEN 'headed' " in crawl_mode_updates[0]
    assert " = 'ctgoodjobs' THEN 'headless' " in crawl_mode_updates[0]
    assert metadata.bind is engine
```

- [ ] **Step 3: Re-run the targeted Docker test to verify it turns green**

Run:

```bash
docker compose run --rm backend-api python -m pytest -q tests/test_bootstrap_db.py
```

Expected:

```text
1 passed
```

- [ ] **Step 4: Commit the import-boundary fix**

Run:

```bash
git add backend/tests/test_bootstrap_db.py
git commit -m "test: align bootstrap db import contract"
```

### Task 2: Document the backend import contract and official verification commands

**Files:**
- Modify: `backend/tests/conftest.py`
- Modify: `README.md`

- [ ] **Step 1: Add an explicit import-contract comment to the shared backend pytest bootstrap**

Update `backend/tests/conftest.py` to:

```python
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    # Backend tests import modules the same way backend runtime modules do:
    # treat `backend/` as the Python source root and use `app.*` / `scripts.*`
    # instead of `backend.*`.
    sys.path.insert(0, str(BACKEND_ROOT))


@compiles(UUID, "sqlite")
def compile_uuid_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(36)"
```

- [ ] **Step 2: Add a dedicated README section for backend QA verification**

Insert this section into `README.md` after `## Worker-Profile QA` and before `## Backend Migrations`:

````md
## Backend QA

Use these commands when validating backend-only changes or before moving on to deeper runtime work.

### Host path

Install backend development dependencies into your local Python environment first:

```bash
python -m pip install -r backend/requirements-dev.txt
```

Then, from the repo root, run:

```bash
python -m pytest --collect-only -q backend/tests
python -m pytest -q backend/tests
```

### Docker path

Use Docker when you want verification closest to the shared containerized runtime:

```bash
docker compose run --rm backend-api python -m pytest --collect-only -q tests
docker compose run --rm backend-api python -m pytest -q tests
```
````

- [ ] **Step 3: Install backend development dependencies in the host Python environment**

Run:

```bash
python -m pip install -r backend/requirements-dev.txt
```

Expected:

```text
Successfully installed pytest pytest-asyncio pytest-cov black ruff isort mypy ipython debugpy
```

If some packages are already present, the command can instead report them as satisfied and still exit successfully.

- [ ] **Step 4: Run the documented collection-only commands from both supported paths**

Run:

```bash
python -m pytest --collect-only -q backend/tests
docker compose run --rm backend-api python -m pytest --collect-only -q tests
```

Expected:

```text
Collected test list or collection summary with exit code 0
No ModuleNotFoundError
No ERROR collecting tests/test_bootstrap_db.py
```

- [ ] **Step 5: Commit the QA documentation and import-contract note**

Run:

```bash
git add backend/tests/conftest.py README.md
git commit -m "docs: define backend QA verification paths"
```

### Task 3: Prove the dual-path backend QA baseline end to end

**Files:**
- Test: `backend/tests`

- [ ] **Step 1: Run the targeted host and Docker regression test from the documented commands**

Run:

```bash
python -m pytest -q backend/tests/test_bootstrap_db.py
docker compose run --rm backend-api python -m pytest -q tests/test_bootstrap_db.py
```

Expected:

```text
Each command ends with `1 passed`
Neither command shows import or collection errors
```

- [ ] **Step 2: Run the full backend suite from the documented host path**

Run:

```bash
python -m pytest -q backend/tests
```

Expected:

```text
Command exits 0
Output ends with a pytest pass summary
No ERROR collecting
No ModuleNotFoundError
```

- [ ] **Step 3: Run the full backend suite from the documented Docker path**

Run:

```bash
docker compose run --rm backend-api python -m pytest -q tests
```

Expected:

```text
Command exits 0
Output ends with a pytest pass summary
No ERROR collecting
No ModuleNotFoundError
```

- [ ] **Step 4: Treat host-vs-Docker disagreement as a failed iteration, not a follow-up nice-to-have**

If either full-suite command behaves differently, stop and inspect import or working-directory assumptions before touching any crawler/runtime code. Do not widen scope into scheduler UX or proxy behavior until both supported verification paths are coherent.

- [ ] **Step 5: Record the exact verification commands and outcomes in the implementation handoff**

Capture the actual host and Docker commands you ran, plus their pass/fail summaries, in the implementation notes or PR description. No new code should be added in this step.
