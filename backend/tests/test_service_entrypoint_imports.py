from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_retrieval_entrypoint_does_not_load_production_api_router() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import app.retrieval_main; "
                "assert 'app.api.crawl_control' not in sys.modules"
            ),
        ],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
