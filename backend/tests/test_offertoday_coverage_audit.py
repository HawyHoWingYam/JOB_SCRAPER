from __future__ import annotations

from scripts.offertoday_coverage_audit import (
    CoverageAuditResult,
    CoverageFamilyStats,
    render_coverage_audit_report,
)


def test_render_coverage_audit_report_marks_successful_audit() -> None:
    result = CoverageAuditResult(
        target_unique_job_ids=598,
        planned_tasks=4,
        processed_tasks=3,
        global_reported_total=3300,
        global_sample_unique_job_ids=598,
        stopped_early=True,
        last_family_with_new_ids="it_keyword",
        family_order=["it_category", "it_keyword"],
        families={
            "it_category": CoverageFamilyStats(
                search_family="it_category",
                pages_fetched=2,
                listing_rows=20,
                sample_unique_job_ids=400,
                duplicate_job_ids=6,
                failed_pages=0,
                reported_total=2066,
            ),
            "it_keyword": CoverageFamilyStats(
                search_family="it_keyword",
                pages_fetched=1,
                listing_rows=18,
                sample_unique_job_ids=198,
                duplicate_job_ids=6,
                failed_pages=1,
                reported_total=1234,
            ),
        },
    )

    report = render_coverage_audit_report(result)

    assert "OfferToday coverage audit" in report
    assert "Planned tasks: 4" in report
    assert "Processed tasks: 3" in report
    assert "Target unique job IDs: 598" in report
    assert "Global reported total: 3300" in report
    assert "Global sample unique rows: 598" in report
    assert "Target reached: yes" in report
    assert "Shortfall: 0" in report
    assert "Last family with new IDs: it_keyword" in report
    assert "Planned families: it_category, it_keyword" in report
    assert "it_category" in report
    assert "it_keyword" in report
    assert " 2066 " in report
    assert " 1234 " in report


def test_render_coverage_audit_report_shows_shortfall() -> None:
    result = CoverageAuditResult(
        target_unique_job_ids=598,
        planned_tasks=1,
        processed_tasks=1,
        global_reported_total=512,
        global_sample_unique_job_ids=18,
        stopped_early=False,
        last_family_with_new_ids="explicit_keyword",
        family_order=["explicit_keyword"],
        families={
            "explicit_keyword": CoverageFamilyStats(
                search_family="explicit_keyword",
                pages_fetched=1,
                listing_rows=18,
                sample_unique_job_ids=18,
                duplicate_job_ids=0,
                failed_pages=0,
                reported_total=512,
            )
        },
    )

    report = render_coverage_audit_report(result)

    assert "Target reached: no" in report
    assert "Shortfall: 580" in report
