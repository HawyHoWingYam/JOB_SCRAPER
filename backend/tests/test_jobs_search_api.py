from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from app.api import jobs as jobs_api


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)
        self._offset = 0
        self._limit = None
        self._apply_sort = False

    def order_by(self, *args):
        if len(args) != 1 or args[0] is not None:
            self._apply_sort = True
        return self

    def count(self):
        return len(self._rows)

    def offset(self, value):
        self._offset = value
        return self

    def limit(self, value):
        self._limit = value
        return self

    def all(self):
        rows = list(self._rows)
        if self._apply_sort:
            rows.sort(
                key=lambda row: row[0].posted_date or row[0].created_at,
                reverse=True,
            )

        end = None if self._limit is None else self._offset + self._limit
        return rows[self._offset:end]


def _build_job(*, title: str, posted_date, created_at):
    return SimpleNamespace(
        id=uuid4(),
        job_id=f"offertoday:{title.lower().replace(' ', '-')}",
        title=title,
        description=None,
        location="Hong Kong",
        salary_range=None,
        employment_type=None,
        subcategory_id=None,
        job_taxonomy=None,
        posted_date=posted_date,
        created_at=created_at,
    )


def _build_company():
    return SimpleNamespace(name="OfferToday Co")


def test_search_jobs_prioritizes_created_at_when_posted_date_is_missing():
    rows = [
        (_build_job(
            title="Older posted job",
            posted_date=datetime(2026, 6, 1, 9, 0, 0),
            created_at=datetime(2026, 6, 1, 9, 0, 0),
        ), _build_company()),
        (_build_job(
            title="OfferToday detail job",
            posted_date=None,
            created_at=datetime(2026, 6, 2, 9, 0, 0),
        ), _build_company()),
    ]
    query = _FakeQuery(rows)

    response = jobs_api._build_search_response(query, page=1, page_size=24)

    assert response.total == 2
    assert [job.title for job in response.jobs] == [
        "OfferToday detail job",
        "Older posted job",
    ]
    assert response.jobs[0].posted_date is None
