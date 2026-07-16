from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from scripts import ctgoodjobs_headless_probe as probe


def _listing_html(job_id: str = "123456") -> str:
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "Information Technology jobs",
        "numberOfItems": 1,
        "itemListElement": [
            {"url": f"https://jobs.ctgoodjobs.hk/job/{job_id}"},
        ],
    }
    return (
        "<html><head><title>Information Technology jobs</title>"
        f'<script type="application/ld+json">{json.dumps(item_list)}</script>'
        "</head><body></body></html>"
    )


def _detail_html(job_id: str = "123456") -> str:
    job_content = {
        "jobId": job_id,
        "jobTitle": "Software Engineer",
        "companyId": "company-1",
        "companyName": "Example Company",
        "companyUrl": "/company/company-1",
        "startPostDate": "2026-07-01",
        "endPostDate": "2026-08-01",
        "jobDescription": "<p>Build reliable systems.</p>",
        "jobLocations": [{"name": "Hong Kong"}],
        "workTypes": [{"name": "Full-time"}],
    }
    flight_payload = json.dumps({"jobContent": job_content}, separators=(",", ":"))
    encoded_flight_payload = json.dumps(flight_payload)
    job_posting = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Software Engineer",
        "description": "Build reliable systems.",
    }
    return (
        "<html><head><title>Software Engineer</title>"
        '<meta name="description" content="Build reliable systems.">'
        f'<script type="application/ld+json">{json.dumps(job_posting)}</script>'
        f"<script>self.__next_f.push([1,{encoded_flight_payload}]);</script>"
        "</head><body></body></html>"
    )


def _classify(
    *,
    phase: str,
    html: str,
    status_code: int = 200,
    title: str | None = None,
    sample_label: str = "sample-1",
    repetition: int = 1,
    session_label: str = "session-1",
    ordinal: int = 1,
) -> dict:
    url = (
        "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology"
        if phase == "listing"
        else "https://jobs.ctgoodjobs.hk/job/123456"
    )
    return probe.classify_page_observation(
        run_id=str(uuid4()),
        ordinal=ordinal,
        arm="fresh-headless",
        phase=phase,
        session_label=session_label,
        repetition=repetition,
        sample_label=sample_label,
        source_url=url,
        final_url=url,
        status_code=status_code,
        title=title,
        html=html,
        attempts=1,
        elapsed_ms=25,
        captured_at="2026-07-16T08:00:00+00:00",
    )


def test_default_plan_has_approved_bounded_budget() -> None:
    plan = probe.ProbePlan()

    assert probe.calculate_request_budget(plan) == {
        "arms": 4,
        "listing_per_arm": 9,
        "detail_per_arm": 20,
        "total_per_arm": 29,
        "total": 116,
        "request_attempt_ceiling": 116,
    }


def test_request_budget_reports_retry_attempt_ceiling() -> None:
    budget = probe.calculate_request_budget(probe.ProbePlan(), max_attempts=3)

    assert budget["total"] == 116
    assert budget["request_attempt_ceiling"] == 348


def test_sanitize_url_keeps_only_approved_ctgoodjobs_origin_and_path() -> None:
    assert probe.sanitize_url(
        "https://jobs.ctgoodjobs.hk/job/123456?token=secret#fragment"
    ) == "https://jobs.ctgoodjobs.hk/job/123456"

    with pytest.raises(ValueError, match="approved CTGoodJobs host"):
        probe.sanitize_url("https://example.test/job/123456?token=secret")


def test_listing_requires_parser_valid_job_ids() -> None:
    observation = _classify(phase="listing", html=_listing_html())

    assert observation["classification"] == "valid_content"
    assert observation["hard_stop"] is False
    assert observation["parser_result"] == {
        "job_id_count": 1,
        "parser_errors": [],
    }
    assert "html" not in observation


def test_waf_evidence_wins_over_terminal_or_parser_text() -> None:
    observation = _classify(
        phase="detail",
        title="Verify you are human",
        html="<html><title>Verify you are human</title>Sorry, this job has expired</html>",
    )

    assert observation["classification"] == "verification_block"
    assert observation["failure_reason"] == "human_verification"
    assert observation["hard_stop"] is True


def test_aws_waf_captcha_header_is_a_positive_hard_stop() -> None:
    url = "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology"
    observation = probe.classify_page_observation(
        run_id=str(uuid4()),
        ordinal=1,
        arm="headed-baseline",
        phase="listing",
        session_label="session-1",
        repetition=1,
        sample_label="information-technology",
        source_url=url,
        final_url=url,
        status_code=405,
        title="",
        html="<html></html>",
        attempts=1,
        elapsed_ms=25,
        captured_at="2026-07-16T08:00:00+00:00",
        waf_action="captcha",
    )

    assert observation["classification"] == "verification_block"
    assert observation["failure_reason"] == "aws_waf_captcha"
    assert observation["hard_stop"] is True


def test_explicit_terminal_detail_is_not_valid_detail_yield() -> None:
    observation = _classify(
        phase="detail",
        status_code=410,
        html="<html><title>Gone</title></html>",
    )

    assert observation["classification"] == "terminal_unavailable"
    assert observation["failure_reason"] == "http_status_410"
    assert observation["hard_stop"] is False


def test_structurally_invalid_detail_is_not_navigation_success() -> None:
    observation = _classify(
        phase="detail",
        html="<html><title>Ordinary page</title></html>",
    )

    assert observation["classification"] == "structural_invalid"
    assert observation["failure_reason"] == "missing_valid_detail_fields"
    assert observation["hard_stop"] is False


def test_valid_detail_records_coverage_without_raw_body() -> None:
    observation = _classify(phase="detail", html=_detail_html())

    assert observation["classification"] == "valid_content"
    assert observation["parser_result"]["job_id_present"] is True
    assert observation["parser_result"]["title_present"] is True
    assert observation["parser_result"]["company_identity_present"] is True
    assert observation["parser_result"]["description_present"] is True
    assert len(observation["body_sha256"]) == 64
    assert "html" not in json.dumps(observation).lower()


def test_artifact_round_trip_and_hash_tamper_detection(tmp_path: Path) -> None:
    run_id = str(uuid4())
    observations = [
        {
            **_classify(phase="listing", html=_listing_html()),
            "run_id": run_id,
        }
    ]

    artifact_dir = probe.export_probe_artifact(
        root=tmp_path,
        run_id=run_id,
        metadata=probe.build_manifest_metadata(
            plan=probe.ProbePlan(),
            selected_arms=("fresh-headless",),
            cooldown_seconds=1.0,
            timeout_seconds=30.0,
        ),
        observations=observations,
        completion_state="completed",
        failure_reason=None,
        captured_at="2026-07-16T08:00:00+00:00",
    )

    verification = probe.verify_probe_artifact(artifact_dir)
    assert verification.valid is True
    assert verification.issues == ()

    observations_path = artifact_dir / "observations.jsonl"
    observations_path.write_text(
        observations_path.read_text(encoding="utf-8") + "{}\n",
        encoding="utf-8",
    )

    verification = probe.verify_probe_artifact(artifact_dir)
    assert verification.valid is False
    assert "observations_hash_mismatch" in verification.issues


def test_unknown_schema_version_and_secret_fields_fail_closed(tmp_path: Path) -> None:
    run_id = str(uuid4())
    observation = {
        **_classify(phase="listing", html=_listing_html()),
        "run_id": run_id,
    }
    artifact_dir = probe.export_probe_artifact(
        root=tmp_path,
        run_id=run_id,
        metadata=probe.build_manifest_metadata(
            plan=probe.ProbePlan(),
            selected_arms=("plain-http",),
            cooldown_seconds=1.0,
            timeout_seconds=30.0,
        ),
        observations=[observation],
        completion_state="completed",
        failure_reason=None,
        captured_at="2026-07-16T08:00:00+00:00",
    )

    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    verification = probe.verify_probe_artifact(artifact_dir)
    assert verification.valid is False
    assert "unsupported_schema_version" in verification.issues

    with pytest.raises(ValueError, match="unexpected observation fields"):
        probe.export_probe_artifact(
            root=tmp_path,
            run_id=str(uuid4()),
            metadata={},
            observations=[{**observation, "cookie": "secret"}],
            completion_state="completed",
            failure_reason=None,
            captured_at="2026-07-16T08:00:00+00:00",
        )


def test_hard_stop_prefix_is_valid_evidence(tmp_path: Path) -> None:
    run_id = str(uuid4())
    blocked = {
        **_classify(
            phase="detail",
            title="Verify you are human",
            html="<html><title>Verify you are human</title></html>",
        ),
        "run_id": run_id,
    }
    artifact_dir = probe.export_probe_artifact(
        root=tmp_path,
        run_id=run_id,
        metadata=probe.build_manifest_metadata(
            plan=probe.ProbePlan(),
            selected_arms=("fresh-headless",),
            cooldown_seconds=1.0,
            timeout_seconds=30.0,
        ),
        observations=[blocked],
        completion_state="hard_stop",
        failure_reason="verification_block",
        captured_at="2026-07-16T08:00:00+00:00",
    )

    assert probe.verify_probe_artifact(artifact_dir).valid is True


def _viability_observations(arm: str) -> list[dict]:
    observations: list[dict] = []
    ordinal = 0
    for category_index in range(3):
        for repetition in range(1, 4):
            ordinal += 1
            observations.append(
                {
                    **_classify(
                        phase="listing",
                        html=_listing_html(str(100000 + category_index)),
                        sample_label=f"category-{category_index}",
                        repetition=repetition,
                        session_label=f"session-{1 + (ordinal % 2)}",
                        ordinal=ordinal,
                    ),
                    "arm": arm,
                }
            )
    for detail_index in range(10):
        for repetition in range(1, 3):
            ordinal += 1
            observations.append(
                {
                    **_classify(
                        phase="detail",
                        html=_detail_html(str(200000 + detail_index)),
                        sample_label=f"detail-{detail_index}",
                        repetition=repetition,
                        session_label=f"session-{repetition}",
                        ordinal=ordinal,
                    ),
                    "arm": arm,
                }
            )
    return observations


@pytest.mark.parametrize(
    "arm",
    ["plain-http", "fresh-headless", "stateful-headless", "headed-baseline"],
)
def test_operational_viability_requires_full_approved_threshold(arm: str) -> None:
    decision = probe.assess_operational_viability(
        _viability_observations(arm),
        arm=arm,
    )

    assert decision["verdict"] == "operationally_viable"
    assert decision["listing_categories_passing"] == 3
    assert decision["detail_samples_passing"] == 10


def test_partial_or_blocked_evidence_remains_conditional() -> None:
    observations = _viability_observations("fresh-headless")[:-1]
    observations.append(
        {
            **_classify(
                phase="detail",
                title="Verify you are human",
                html="<html><title>Verify you are human</title></html>",
                sample_label="detail-9",
                repetition=2,
                session_label="session-2",
                ordinal=len(observations) + 1,
            ),
            "arm": "fresh-headless",
        }
    )

    decision = probe.assess_operational_viability(
        observations,
        arm="fresh-headless",
    )

    assert decision["verdict"] == "conditional"
    assert decision["verification_blocks"] == 1


@pytest.mark.parametrize(
    ("completion_state", "verification_valid", "verdict", "expected"),
    [
        ("completed", True, "operationally_viable", 0),
        ("completed", True, "conditional", 3),
        ("partial", True, "conditional", 3),
        ("hard_stop", True, "conditional", 4),
        ("failed", True, "conditional", 5),
        ("completed", False, "operationally_viable", 5),
    ],
)
def test_exit_codes_distinguish_decision_hard_stop_and_evidence_failure(
    completion_state: str,
    verification_valid: bool,
    verdict: str,
    expected: int,
) -> None:
    assert (
        probe.resolve_probe_exit_code(
            completion_state=completion_state,
            verification_valid=verification_valid,
            decisions={"plain-http": {"verdict": verdict}},
        )
        == expected
    )


def test_cli_plan_is_offline_and_run_requires_explicit_confirmation(capsys) -> None:
    assert probe.main(["--plan"]) == 0
    output = capsys.readouterr().out
    assert '"total": 116' in output

    with pytest.raises(SystemExit) as exc_info:
        probe.main(["--arm", "plain-http"])
    assert exc_info.value.code == 2


def test_cli_maps_unexpected_pre_artifact_failure_to_evidence_exit(
    monkeypatch,
    capsys,
) -> None:
    async def fail_before_artifact(**_kwargs):
        raise RuntimeError("must not escape as an unbounded CLI traceback")

    monkeypatch.setattr(probe, "_run_live_probe", fail_before_artifact)

    assert (
        probe.main(
            [
                "--arm",
                "plain-http",
                "--category-count",
                "1",
                "--listing-repetitions",
                "1",
                "--detail-count",
                "1",
                "--detail-repetitions",
                "1",
                "--browser-sessions",
                "1",
                "--confirm-live-research",
            ]
        )
        == 5
    )
    assert '"failure_reason": "unexpected_failure"' in capsys.readouterr().out
