from __future__ import annotations

from typing import Any


def is_complete_offertoday_job(job: Any) -> bool:
    """Return whether a published OfferToday Job has all required detail fields."""

    return all(
        (
            str(getattr(job, "source_site", "") or "").strip().lower()
            == "offertoday",
            bool(str(getattr(job, "source_job_id", "") or "").strip()),
            bool(str(getattr(job, "title", "") or "").strip()),
            bool(str(getattr(job, "description", "") or "").strip()),
            getattr(job, "company_id", None) is not None,
        )
    )
