from __future__ import annotations

import json
import hashlib
from pathlib import Path

from scripts.jev_skill_evaluation import main


FIXTURE = Path(__file__).parent / "fixtures" / "jev_skill_controlled_v1.jsonl"


def test_validate_and_plan_do_not_dispatch_or_enforce_local_money(capsys) -> None:
    assert main(["validate", "--controlled", str(FIXTURE)]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated == {"controlled_cases": 17, "valid": True}

    assert (
        main(
            [
                "plan",
                "--controlled",
                str(FIXTURE),
                "--split",
                "development",
                "--limit",
                "3",
            ]
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    assert plan == {
        "selected": 3,
        "monetary_authority": "jev_api_console",
        "paid_requests_started": 0,
    }


def test_run_requires_explicit_paid_confirmation(tmp_path: Path, capsys) -> None:
    output = tmp_path / "observations.jsonl"
    assert (
        main(
            [
                "run",
                "--controlled",
                str(FIXTURE),
                "--output",
                str(output),
                "--state-db",
                str(tmp_path / "state.sqlite"),
            ]
        )
        == 2
    )
    assert "--confirm-paid-evaluation" in capsys.readouterr().err
    assert not output.exists()


def test_report_writes_deterministic_inconclusive_outputs(
    tmp_path: Path,
    capsys,
) -> None:
    observations = tmp_path / "observations.jsonl"
    observations.write_text(
        json.dumps(
            {
                "case_id": "smoke",
                "split": "development",
                "decision_kind": "evidence_support",
                "status": "unavailable",
                "error_code": "http_401",
                "manifest_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            }
        )
        + "\n"
    )
    json_output = tmp_path / "report.json"
    markdown_output = tmp_path / "report.md"

    assert (
        main(
            [
                "report",
                "--controlled",
                str(FIXTURE),
                "--observations",
                str(observations),
                "--json-output",
                str(json_output),
                "--markdown-output",
                str(markdown_output),
            ]
        )
        == 0
    )

    report = json.loads(json_output.read_text())
    assert report["decision"] == "inconclusive"
    assert report["execution"]["unavailable"] == 1
    assert report["execution"]["provider_reported_microdollars"] == 0
    assert "Decision: **inconclusive**" in markdown_output.read_text()
    assert json.loads(capsys.readouterr().out) == {"decision": "inconclusive"}


def test_report_rejects_observations_from_another_manifest(
    tmp_path: Path, capsys
) -> None:
    observations = tmp_path / "observations.jsonl"
    observations.write_text(
        json.dumps(
            {
                "case_id": "smoke",
                "split": "development",
                "decision_kind": "evidence_support",
                "status": "unavailable",
                "manifest_sha256": "a" * 64,
            }
        )
        + "\n"
    )

    assert (
        main(
            [
                "report",
                "--controlled",
                str(FIXTURE),
                "--observations",
                str(observations),
                "--json-output",
                str(tmp_path / "report.json"),
                "--markdown-output",
                str(tmp_path / "report.md"),
            ]
        )
        == 2
    )
    assert "manifest hash" in capsys.readouterr().err


def test_report_rejects_unbound_observations(tmp_path: Path, capsys) -> None:
    observations = tmp_path / "observations.jsonl"
    observations.write_text(
        json.dumps(
            {
                "case_id": "smoke",
                "split": "development",
                "decision_kind": "evidence_support",
                "status": "unavailable",
            }
        )
        + "\n"
    )

    assert (
        main(
            [
                "report",
                "--controlled",
                str(FIXTURE),
                "--observations",
                str(observations),
                "--json-output",
                str(tmp_path / "report.json"),
                "--markdown-output",
                str(tmp_path / "report.md"),
            ]
        )
        == 2
    )
    assert "manifest hash" in capsys.readouterr().err
