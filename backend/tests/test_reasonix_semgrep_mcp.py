from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[2] / ".reasonix" / "scripts" / "reasonix_semgrep_mcp.py"
SPEC = importlib.util.spec_from_file_location("reasonix_semgrep_mcp", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_parse_semgrep_output_extracts_findings():
    payload = {
        "results": [
            {
                "check_id": "python-eval",
                "path": "backend/app/api/jobs.py",
                "start": {"line": 12},
                "end": {"line": 13},
                "extra": {
                    "message": "Avoid eval",
                    "severity": "ERROR",
                    "lines": "eval(user_input)",
                },
            }
        ],
        "errors": [],
        "paths": {"scanned": ["backend/app/api/jobs.py"]},
        "engine_requested": "OSS",
    }

    result = MODULE.parse_semgrep_output(
        stdout=json.dumps(payload),
        stderr="warning text",
        returncode=1,
        max_findings=10,
    )

    assert result["ok"] is True
    assert result["finding_count"] == 1
    assert result["error_count"] == 0
    assert result["engine_requested"] == "OSS"
    assert result["findings"][0] == {
        "check_id": "python-eval",
        "path": "backend/app/api/jobs.py",
        "start_line": 12,
        "end_line": 13,
        "severity": "ERROR",
        "message": "Avoid eval",
        "lines": "eval(user_input)",
    }


def test_parse_semgrep_output_marks_errors_and_invalid_json():
    result = MODULE.parse_semgrep_output(
        stdout="not-json",
        stderr="stderr text",
        returncode=2,
        max_findings=5,
    )

    assert result["ok"] is False
    assert result["finding_count"] == 0
    assert result["error_count"] == 1
    assert result["errors"][0]["message"] == "Failed to parse Semgrep JSON output"
    assert result["stderr"] == "stderr text"


def test_run_semgrep_uses_devnull_stdin(monkeypatch):
    captured: dict[str, object] = {}

    class FakeCompleted:
        stdout = b'{"results":[],"errors":[],"paths":{"scanned":[]},"engine_requested":"OSS"}'
        stderr = b""
        returncode = 0

    def fake_run(command, *, capture_output, check, env, stdin):
        captured["command"] = command
        captured["capture_output"] = capture_output
        captured["check"] = check
        captured["env"] = env
        captured["stdin"] = stdin
        return FakeCompleted()

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    MODULE.run_semgrep(["semgrep", "scan"], max_findings=5)

    assert captured["capture_output"] is True
    assert captured["check"] is False
    assert captured["stdin"] is MODULE.subprocess.DEVNULL
