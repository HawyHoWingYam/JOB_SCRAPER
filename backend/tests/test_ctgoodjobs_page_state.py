from __future__ import annotations

from app.scraper.ctgoodjobs.page_state import (
    CTGoodJobsTerminalUnavailableError,
    classify_ctgoodjobs_detail_page,
)


def test_ctgoodjobs_http_gone_is_terminal_unavailable() -> None:
    evidence = classify_ctgoodjobs_detail_page(
        status_code=410,
        final_url="https://jobs.ctgoodjobs.hk/job/expired-1",
        title="",
        html="",
    )

    assert evidence is not None
    assert evidence.reason == "http_status_410"
    error = CTGoodJobsTerminalUnavailableError.from_evidence(evidence)
    assert error.reason == "http_status_410"
    assert "expired-1" in error.url


def test_ctgoodjobs_explicit_page_state_is_terminal_unavailable() -> None:
    evidence = classify_ctgoodjobs_detail_page(
        status_code=200,
        final_url="https://jobs.ctgoodjobs.hk/job/expired-2",
        title="",
        html=(
            '<main data-page-state="job-not-found">'
            "This job is no longer available."
            "</main>"
        ),
    )

    assert evidence is not None
    assert evidence.reason == "job_no_longer_available"


def test_ctgoodjobs_live_expired_page_is_terminal_unavailable() -> None:
    evidence = classify_ctgoodjobs_detail_page(
        status_code=200,
        final_url="https://jobs.ctgoodjobs.hk/job/10185476/network-engineer",
        title=(
            "Network Engineer - The Wing On Department Stores "
            "(Hong Kong) Limited | CTgoodjobs"
        ),
        html=(
            '<section class="jd--edge jd--expired full-height">'
            '<div class="container"><div class="msg">'
            '<h3>Sorry, this job has expired.</h3>'
            '<div class="job__info">'
            '<div class="job__title">Network Engineer</div>'
            '<div class="job__company">'
            "The Wing On Department Stores (Hong Kong) Limited"
            "</div></div></div></div></section>"
        ),
    )

    assert evidence is not None
    assert evidence.reason == "job_expired"


def test_ctgoodjobs_job_description_text_is_not_page_state_evidence() -> None:
    assert (
        classify_ctgoodjobs_detail_page(
            status_code=200,
            final_url="https://jobs.ctgoodjobs.hk/job/active-job",
            title="Software Engineer",
            html=(
                "<html><body><main><article>"
                "Maintain a migration banner saying this job has expired."
                "</article></main></body></html>"
            ),
        )
        is None
    )


def test_ctgoodjobs_missing_fields_are_not_page_state_evidence() -> None:
    assert (
        classify_ctgoodjobs_detail_page(
            status_code=200,
            final_url="https://jobs.ctgoodjobs.hk/job/unknown-shape",
            title="",
            html="<html><body><main></main></body></html>",
        )
        is None
    )
