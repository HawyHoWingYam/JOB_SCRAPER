from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[2] / ".reasonix" / "scripts" / "reasonix_plugin_smoke_test.py"
SPEC = importlib.util.spec_from_file_location("reasonix_plugin_smoke_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_evaluate_case_passes_on_explicit_pass_line():
    case = MODULE.CASES["postgres"]
    result = MODULE.evaluate_case(case, stdout="PASS\ncompanies", stderr="", returncode=0)

    assert result["passed"] is True
    assert result["status_line"] == "PASS"


def test_evaluate_case_allows_transient_initializing_before_pass():
    case = MODULE.CASES["redis"]
    result = MODULE.evaluate_case(
        case,
        stdout="still initializing\nRESULT: PASS\nstream keys listed",
        stderr="",
        returncode=0,
    )

    assert result["passed"] is True
    assert "still initializing" in result["combined_output"]


def test_evaluate_case_fails_on_actual_forbidden_marker():
    case = MODULE.CASES["semgrep"]
    result = MODULE.evaluate_case(
        case,
        stdout="RESULT: PASS\ncontext deadline exceeded",
        stderr="",
        returncode=0,
    )

    assert result["passed"] is False
    assert "context deadline exceeded" in result["combined_output"]


def test_decode_output_replaces_invalid_utf8_bytes():
    assert MODULE.decode_output(b"ok\xe2") == "ok\ufffd"


def test_evaluate_case_handles_missing_stream_text():
    case = MODULE.CASES["semgrep"]
    result = MODULE.evaluate_case(case, stdout=None, stderr=None, returncode=1)

    assert result["passed"] is False
    assert result["combined_output"] == ""


def test_render_payload_escapes_non_ascii_text():
    rendered = MODULE.render_payload({"results": [{"combined_output": "⊘ 失败"}]})

    assert "\\u2298" in rendered
    assert "\\u5931\\u8d25" in rendered
