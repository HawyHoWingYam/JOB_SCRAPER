from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from scripts.review_offertoday_job_detail_keywords import (
    CandidateTerm,
    CrossSourceCandidateTerm,
    JobEvidence,
    ProbeBudgetExceeded,
    ProbeRequestBudget,
    ProbeTarget,
    analyze_first_pass,
    build_corpus_snapshot,
    build_cross_source_probe_plan,
    build_cross_source_review_payload,
    build_cross_source_snapshot,
    build_probe_plan,
    build_review_payload,
    finalize_probe_analysis,
    matches_term,
    normalize_corpus_text,
    read_only_session,
    render_cross_source_markdown,
    render_markdown_review,
    title_language,
)


def _path(*nodes: tuple[str, str]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "source_position": index,
            "native_depth": index,
            "classification_id": classification_id,
            "native_id": classification_id.rsplit(":", 1)[-1],
            "label": label,
            "is_primary": False,
        }
        for index, (classification_id, label) in enumerate(nodes)
    )


def _job(
    source_job_id: str,
    title: str,
    description: str,
    *,
    child: str = "offertoday:118009",
) -> JobEvidence:
    return JobEvidence(
        job_id=f"uuid-{source_job_id}",
        source_job_id=source_job_id,
        title=title,
        description=description,
        company_name="Example Limited",
        posted_date="2026-07-30T00:00:00",
        paths=(
            _path(
                ("offertoday:118000", "資訊科技"),
                (child, "軟體工程師"),
            ),
        ),
    )


def _keyword(keyword: str, *, enabled: bool = True) -> dict[str, object]:
    return {
        "entry_id": f"entry-{keyword}",
        "classification_id": "offertoday:118000",
        "classification_label": "Information Technology",
        "keyword": keyword,
        "normalized_keyword": keyword.casefold(),
        "enabled": enabled,
        "notes": "",
        "last_new_job_ids": None,
        "last_duplicate_rate": None,
        "last_run_at": None,
    }


def _classifications() -> list[dict[str, object]]:
    return [
        {
            "classification_id": "offertoday:118000",
            "native_id": "118000",
            "label": "Information Technology",
            "parent_classification_id": None,
            "depth": 0,
            "is_top_level": True,
            "is_active": True,
        },
        {
            "classification_id": "offertoday:118009",
            "native_id": "118009",
            "label": "軟體工程師",
            "parent_classification_id": "offertoday:118000",
            "depth": 1,
            "is_top_level": False,
            "is_active": True,
        },
    ]


def test_matching_normalizes_unicode_but_keeps_latin_boundaries() -> None:
    assert normalize_corpus_text("  POWER\u3000BI  ") == "power bi"
    assert matches_term("Power BI Developer", "POWER BI")
    assert matches_term("C / C++ Engineer", "C")
    assert not matches_term("Scalable platform", "C")
    assert matches_term("桌面運維工程師", "桌面運維")
    assert title_language("Frontend 前端工程師") == "mixed"


def test_corpus_snapshot_counts_distinct_jobs_and_preserves_multi_path_evidence() -> None:
    jobs = (
        _job("job-1", "Helpdesk Engineer", "Microsoft support and CRM"),
        _job("job-2", "Helpdesk Officer", "Microsoft desktop support"),
        replace(
            _job("job-3", "Helpdesk Analyst", "Microsoft UAT support"),
            paths=(
                _path(
                    ("offertoday:118000", "資訊科技"),
                    ("offertoday:118009", "軟體工程師"),
                ),
                _path(
                    ("offertoday:112000", "工程師"),
                    ("offertoday:112002", "品質保證"),
                ),
            ),
        ),
    )
    candidates = (
        CandidateTerm(
            classification_id="offertoday:118000",
            keyword="Helpdesk",
            family="it_support",
            candidate_kind="role_phrase",
            rationale="Repeated role phrase",
        ),
    )

    snapshot = build_corpus_snapshot(
        jobs=jobs,
        classifications=_classifications(),
        keyword_entries=(_keyword("support"),),
        candidates=candidates,
        staging_summary={"rows": 3},
        min_support=3,
        example_limit=2,
    )

    assert snapshot["population"]["published_jobs"] == 3
    assert snapshot["population"]["source_classification_path_count"] == 4
    assert snapshot["population"]["explicit_primary_path_count"] == 0
    assert snapshot["candidates"][0]["corpus_status"] == "probe_addition_candidate"
    assert snapshot["candidates"][0]["detail_match_count"] == 3
    assert len(snapshot["candidates"][0]["examples"]) == 2
    assert snapshot["packs"][0]["terms_with_execution_evidence"] == 0


class _FakeSession:
    def __init__(self, dialect: str = "postgresql") -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))
        self.executed: list[tuple[str, object]] = []
        self.rolled_back = False
        self.closed = False

    def get_bind(self):
        return self.bind

    def execute(self, statement, parameters=None):
        self.executed.append((str(statement), parameters))

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_read_only_session_enforces_postgres_and_rolls_back_on_success() -> None:
    session = _FakeSession()
    with read_only_session(lambda: session, statement_timeout_ms=1234) as active:
        assert active is session

    assert session.executed[0][0] == "SET TRANSACTION READ ONLY"
    assert session.executed[1][0] == "SET LOCAL statement_timeout = :timeout"
    assert session.executed[1][1] == {"timeout": "1234ms"}
    assert session.rolled_back
    assert session.closed


def test_read_only_session_refuses_non_postgres_before_analysis() -> None:
    session = _FakeSession("sqlite")
    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        with read_only_session(lambda: session):
            raise AssertionError("must not yield")
    assert session.rolled_back
    assert session.closed


def _probe_corpus() -> dict[str, object]:
    return {
        "schema_version": 1,
        "extracted_at": "2026-08-04T00:00:00+00:00",
        "population": {
            "published_jobs": 3,
            "posted_date_min": "2026-07-30T00:00:00",
            "posted_date_max": "2026-07-30T00:00:00",
            "source_classification_path_count": 3,
            "explicit_primary_path_count": 0,
            "title_language_counts": {"latin": 3},
        },
        "semantic_coverage": {
            "title_coverage_rate": 1.0,
            "detail_coverage_rate": 1.0,
        },
        "limitations": [],
        "packs": [],
        "classifications": _classifications(),
        "keywords": [
            {
                **_keyword("support"),
                "title_match_count": 3,
                "detail_match_count": 12,
            },
            {
                **_keyword("quantum"),
                "title_match_count": 0,
                "detail_match_count": 1,
            },
        ],
        "candidates": [
            {
                "classification_id": "offertoday:118000",
                "keyword": "Helpdesk",
                "normalized_keyword": "helpdesk",
                "family": "it_support",
                "candidate_kind": "role_phrase",
                "corpus_status": "probe_addition_candidate",
                "title_match_count": 4,
                "detail_match_count": 8,
                "uncovered_title_match_count": 2,
            }
        ],
    }


def test_probe_plan_accounts_for_every_enabled_current_term_and_hard_cap() -> None:
    plan = build_probe_plan(
        _probe_corpus(),
        max_additions=30,
        max_retirements=30,
        first_pass_pages=2,
        second_pass_pages=1,
        request_cap=250,
    )

    assert len(plan["native_targets"]) == 2
    assert [target.keyword for target in plan["current_targets"]] == [
        "quantum",
        "support",
    ]
    assert plan["addition_targets"][0].pages == 2
    assert plan["first_pass_request_max"] == 6
    assert plan["addition_confirmation_request_max"] == 1
    with pytest.raises(ValueError, match="inside request cap"):
        build_probe_plan(
            _probe_corpus(),
            max_additions=30,
            max_retirements=30,
            first_pass_pages=2,
            second_pass_pages=1,
            request_cap=7,
        )


def test_probe_budget_refuses_request_before_exceeding_cap() -> None:
    budget = ProbeRequestBudget(2)
    budget.consume()
    budget.consume()
    with pytest.raises(ProbeBudgetExceeded):
        budget.consume()
    assert budget.started == 2


def test_contribution_analysis_requires_independent_retirement_repeat() -> None:
    current_targets = (
        ProbeTarget(
            key="current:support",
            kind="current_keyword",
            classification_id="offertoday:118000",
            category_id=118000,
            keyword="support",
            pages=1,
            corpus_detail_matches=12,
        ),
        ProbeTarget(
            key="current:quantum",
            kind="current_keyword",
            classification_id="offertoday:118000",
            category_id=118000,
            keyword="quantum",
            pages=1,
            corpus_detail_matches=0,
        ),
    )
    first_passes = [
        {
            "status": "complete",
            "targets": [
                {"key": "native:offertoday:118000", "job_ids": ["1", "2"]},
                {"key": "current:support", "job_ids": ["2", "3"]},
                {"key": "current:quantum", "job_ids": ["2"]},
                {"key": "addition:helpdesk", "job_ids": ["2", "4"]},
            ]
        }
    ]
    first = analyze_first_pass(first_passes, current_targets, max_retirements=30)
    assert first["current_contribution"]["current:support"]["leave_one_out_new"] == 1
    assert first["current_contribution"]["current:quantum"]["leave_one_out_new"] == 0
    assert first["addition_contribution"]["addition:helpdesk"]["new_vs_current_pack"] == 1
    assert [target.keyword for target in first["retirement_targets"]] == ["quantum"]

    all_passes = [
        *first_passes,
        {
            "status": "complete",
            "targets": [
                {"key": "native-repeat:offertoday:118000", "job_ids": ["1"]},
                {"key": "retirement-repeat:quantum", "job_ids": ["2"]},
            ],
        },
    ]
    corpus = _probe_corpus()
    final = finalize_probe_analysis(
        corpus=corpus,
        passes=all_passes,
        first_analysis=first,
        retirement_targets=first["retirement_targets"],
    )
    assert final["verdict"] == "insufficient"
    assert final["addition_results"]["addition:helpdesk"]["decision"] == "add"
    assert final["retirement_results"]["current:quantum"]["decision"] == "retire_candidate"

    report = render_markdown_review(
        build_review_payload(
            corpus,
            {
                "status": "complete",
                "requests_started": 6,
                "request_cap": 250,
                "analysis": final,
            },
        )
    )
    assert "### Recall benefit and precision risk" in report
    assert "| Add `Helpdesk` | 1 sampled ID(s) beyond the current pack" in report
    assert "| Retire `quantum` | Removes one query after 0 corpus matches" in report
    assert "reversible CSV preview/confirm change" in report


def test_markdown_report_is_deterministic_and_accounts_for_current_terms() -> None:
    jobs = (
        _job("job-1", "Helpdesk Engineer", "Microsoft support"),
        _job("job-2", "Helpdesk Officer", "Microsoft support"),
        _job("job-3", "Helpdesk Analyst", "Microsoft support"),
    )
    corpus = build_corpus_snapshot(
        jobs=jobs,
        classifications=_classifications(),
        keyword_entries=(_keyword("support"),),
        candidates=(
            CandidateTerm(
                "offertoday:118000",
                "Helpdesk",
                "it_support",
                "role_phrase",
                "Repeated role phrase",
            ),
        ),
        staging_summary={"rows": 3},
        extracted_at=SimpleNamespace(isoformat=lambda: "2026-08-04T00:00:00+00:00"),
    )
    review = build_review_payload(corpus, None)
    first = render_markdown_review(review)
    second = render_markdown_review(review)

    assert first == second
    assert "INCONCLUSIVE" in first
    assert "| support | yes |" in first
    assert "No Keyword Pack change is justified" in first


def test_cross_source_snapshot_counts_each_source_and_requires_title_support() -> None:
    jobsdb_jobs = tuple(
        replace(
            _job(f"jobsdb-{index}", "Databricks Engineer", "Databricks platform"),
            paths=(_path(("jobsdb:6281", "ICT")),),
        )
        for index in range(3)
    )
    ctgoodjobs_jobs = tuple(
        replace(
            _job(f"ct-{index}", "Data Engineer", "Databricks platform"),
            paths=(_path(("ctgoodjobs:021", "IT")),),
        )
        for index in range(3)
    )
    offertoday_jobs = tuple(
        _job(f"offer-{index}", "Data Engineer", "Databricks platform")
        for index in range(3)
    )
    keyword_entries = (_keyword("support"),)
    baseline = {
        "kind": "offertoday_keyword_corpus_snapshot",
        "population": {"published_jobs": 3},
        "keywords": list(keyword_entries),
    }
    candidate = CrossSourceCandidateTerm(
        classification_id="offertoday:118000",
        keyword="Databricks",
        family="data_platform",
        candidate_kind="product",
        discovery_sources="jobsdb+ctgoodjobs",
        rationale="Repeated platform",
        candidate_scope="new",
        analyst_disposition="evaluate",
        risk="Tool dependency",
    )

    snapshot = build_cross_source_snapshot(
        jobs_by_source={
            "jobsdb": jobsdb_jobs,
            "ctgoodjobs": ctgoodjobs_jobs,
        },
        usable_job_counts={"jobsdb": 4, "ctgoodjobs": 3},
        offertoday_jobs=offertoday_jobs,
        keyword_entries=keyword_entries,
        candidates=(candidate,),
        baseline_corpus=baseline,
        discovery_limit=20,
        example_limit=2,
        extracted_at=SimpleNamespace(isoformat=lambda: "2026-08-04T00:00:00+00:00"),
    )

    row = snapshot["candidates"][0]
    assert snapshot["population"]["jobsdb"]["included_it_jobs"] == 3
    assert snapshot["population"]["jobsdb"]["excluded_without_it_root"] == 1
    assert row["source_evidence"]["jobsdb"]["detail_match_count"] == 3
    assert row["source_evidence"]["ctgoodjobs"]["detail_match_count"] == 3
    assert row["pre_probe_disposition"] == "probe_candidate"
    assert row["source_evidence"]["jobsdb"]["examples"][0]["source_site"] == "jobsdb"
    assert snapshot["discovery_inventory"]


def test_cross_source_probe_plan_enforces_approved_hard_cap() -> None:
    corpus = {
        "candidates": [
            {
                "candidate_scope": "new",
                "pre_probe_disposition": "probe_candidate",
                "normalized_keyword": "databricks",
                "keyword": "Databricks",
                "source_evidence": {
                    "jobsdb": {"title_match_count": 4, "detail_match_count": 10},
                    "ctgoodjobs": {"title_match_count": 3, "detail_match_count": 8},
                    "offertoday": {"title_match_count": 1, "detail_match_count": 3},
                },
            }
        ]
    }
    targets = build_cross_source_probe_plan(
        corpus,
        max_additions=30,
        pages_per_candidate=2,
        request_cap=60,
    )
    assert [target.keyword for target in targets] == ["Databricks"]
    assert targets[0].pages == 2
    with pytest.raises(ValueError, match="cannot exceed 60"):
        build_cross_source_probe_plan(
            corpus,
            max_additions=30,
            pages_per_candidate=2,
            request_cap=61,
        )
    with pytest.raises(ValueError, match="two pages"):
        build_cross_source_probe_plan(
            corpus,
            max_additions=30,
            pages_per_candidate=3,
            request_cap=60,
        )


def test_cross_source_report_is_deterministic_and_keeps_variants_separate() -> None:
    corpus = {
        "schema_version": 1,
        "kind": "offertoday_keyword_cross_source_corpus",
        "source_roots": {
            "jobsdb": "jobsdb:6281",
            "ctgoodjobs": "ctgoodjobs:021",
        },
        "population": {
            "jobsdb": {
                "usable_jobs": 1,
                "included_it_jobs": 1,
                "excluded_without_it_root": 0,
                "posted_date_min": "2026-08-04",
                "posted_date_max": "2026-08-04",
            }
        },
        "limitations": [],
        "candidates": [
            {
                "classification_id": "offertoday:118000",
                "keyword": "Microsoft 365",
                "normalized_keyword": "microsoft 365",
                "family": "microsoft",
                "candidate_kind": "product_variant",
                "candidate_scope": "new",
                "pre_probe_disposition": "probe_candidate",
                "risk": "Overlap",
                "source_evidence": {
                    source: {
                        "title_match_count": 2,
                        "detail_match_count": 3,
                        "examples": [],
                    }
                    for source in ("jobsdb", "ctgoodjobs", "offertoday")
                },
            }
        ],
    }
    probe = {
        "status": "complete",
        "requests_started": 2,
        "request_cap": 60,
        "finished_at": "2026-08-04T01:00:00+00:00",
        "archived_baseline": {"finished_at": "2026-08-04T00:00:00+00:00"},
        "analysis": {
            "candidate_results": {
                "cross-source:microsoft 365": {
                    "keyword": "Microsoft 365",
                    "distinct_job_ids": 10,
                    "new_vs_archived_current_pack": 2,
                    "decision": "supported_addition",
                }
            }
        },
        "limitations": [],
    }
    review = build_cross_source_review_payload(corpus, probe)
    first = render_cross_source_markdown(review)
    second = render_cross_source_markdown(review)

    assert first == second
    assert review["recommendations"]["variants_or_replacements"] == [
        "Microsoft 365"
    ]
    assert "variant_or_replacement" in first
