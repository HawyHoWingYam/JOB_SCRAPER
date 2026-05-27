from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    # Backend tests follow the same import model as backend runtime modules:
    # treat `backend/` as the Python source root and import via `app.*`
    # or `scripts.*`, not `backend.*`.
    sys.path.insert(0, str(BACKEND_ROOT))


@compiles(UUID, "sqlite")
def compile_uuid_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(36)"
