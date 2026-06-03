import pytest

from app.services.company_enrichment_service import normalize_company_description


def test_normalize_company_description_rejects_process_narration():
    with pytest.raises(ValueError, match="final company description"):
        normalize_company_description(
            "Searching current public sources for the company first, then I will condense "
            "that into a short description."
        )


def test_normalize_company_description_compacts_whitespace_for_valid_text():
    description = (
        "  Example Co is a Hong Kong technology company. \n\n"
        "It hires software and operations talent across regional teams.  "
    )

    assert normalize_company_description(description) == (
        "Example Co is a Hong Kong technology company. "
        "It hires software and operations talent across regional teams."
    )


def test_normalize_company_description_strips_markdown_links():
    description = (
        "[Example Co](https://example.com) is a Hong Kong technology company. "
        "It hires software and operations talent across regional teams."
    )

    assert normalize_company_description(description) == (
        "Example Co is a Hong Kong technology company. "
        "It hires software and operations talent across regional teams."
    )
