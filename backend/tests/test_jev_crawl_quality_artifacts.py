from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.jev_crawl_quality import (
    CrawlQualityArtifactError,
    load_crawl_quality_cases,
)


FIXTURE = Path(__file__).parent / "fixtures" / "jev_crawl_quality_controlled_v1.jsonl"


def test_controlled_crawl_quality_fixture_has_required_sources_languages_and_scenarios() -> (
    None
):
    cases = load_crawl_quality_cases(FIXTURE)

    assert len(cases) >= 18
    assert {case.split for case in cases} == {"development", "held_out"}
    assert {case.source_site for case in cases} == {
        "jobsdb",
        "ctgoodjobs",
        "offertoday",
    }
    assert {case.language for case in cases} >= {"en", "zh-Hant", "mixed"}
    assert {case.expected for case in cases} == {
        "usable_job_detail",
        "quality_problem",
        "insufficient",
    }
    assert {case.problem_kind for case in cases} >= {
        "none",
        "empty_or_short",
        "access_wall",
        "terminal_page",
        "listing_or_template",
        "truncated",
        "irrelevant",
        "insufficient",
    }
    assert {tag for case in cases for tag in case.scenario_tags} >= {
        "valid_detail",
        "empty_or_short",
        "login_wall",
        "waf_challenge",
        "terminal_unavailable",
        "listing_as_detail",
        "truncated",
        "template_heavy",
        "missing_evidence",
        "option_reordered",
    }
    dev_groups = {case.group_id for case in cases if case.split == "development"}
    held_groups = {case.group_id for case in cases if case.split == "held_out"}
    assert dev_groups.isdisjoint(held_groups)


def test_controlled_crawl_quality_fixture_rejects_hash_drift_leakage_and_extra_fields(
    tmp_path: Path,
) -> None:
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    rows[0]["evidence_excerpt"] += " changed"
    drifted = tmp_path / "drifted.jsonl"
    drifted.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(CrawlQualityArtifactError, match="evidence_sha256"):
        load_crawl_quality_cases(drifted)

    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    rows[1]["group_id"] = rows[0]["group_id"]
    rows[1]["split"] = "held_out"
    leaking = tmp_path / "leaking.jsonl"
    leaking.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(CrawlQualityArtifactError, match="group leakage"):
        load_crawl_quality_cases(leaking)

    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    rows[0]["credential"] = "forbidden"
    extra = tmp_path / "extra.jsonl"
    extra.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(CrawlQualityArtifactError, match="invalid crawl quality case"):
        load_crawl_quality_cases(extra)
