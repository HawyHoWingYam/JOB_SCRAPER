from __future__ import annotations

from app.services.enrichment_run_service import EnrichmentRunService


class _FakeQuery:
    def __init__(self, *, count_result=None, first_result=None, one_result=None):
        self.count_result = count_result
        self.first_result = first_result
        self.one_result = one_result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def one(self):
        return self.one_result

    def count(self):
        return self.count_result

    def first(self):
        return self.first_result


class _FakeDB:
    def __init__(self, queries):
        self._queries = list(queries)
        self.query_calls = []

    def query(self, *entities):
        self.query_calls.append(entities)
        if not self._queries:
            raise AssertionError("Unexpected query call")
        return self._queries.pop(0)


def test_get_overview_skips_failed_job_scan_when_failed_item_count_is_zero(monkeypatch):
    db = _FakeDB(
        [
            _FakeQuery(one_result=(400, 4)),
            _FakeQuery(one_result=(0, 1)),
            _FakeQuery(count_result=0),
            _FakeQuery(first_result=None),
        ]
    )
    service = EnrichmentRunService(db)

    def fail_failed_job_scan():
        raise AssertionError("failed job scan should be skipped when there are no failed items")

    monkeypatch.setattr(service, "_count_current_failed_jobs", fail_failed_job_scan)

    overview = service.get_overview()

    assert overview["total_jobs"] == 400
    assert overview["enriched_jobs"] == 4
    assert overview["running_runs"] == 0
    assert overview["active_runs"] == 1
    assert overview["failed_items"] == 0
    assert overview["failed_jobs"] == 0


def test_get_overview_scans_failed_jobs_when_failed_items_exist(monkeypatch):
    db = _FakeDB(
        [
            _FakeQuery(one_result=(400, 4)),
            _FakeQuery(one_result=(0, 1)),
            _FakeQuery(count_result=3),
            _FakeQuery(first_result=None),
        ]
    )
    service = EnrichmentRunService(db)
    failed_job_scan_calls = []

    def resolve_failed_job_scan():
        failed_job_scan_calls.append(True)
        return 2

    monkeypatch.setattr(service, "_count_current_failed_jobs", resolve_failed_job_scan)

    overview = service.get_overview()

    assert overview["total_jobs"] == 400
    assert overview["enriched_jobs"] == 4
    assert overview["running_runs"] == 0
    assert overview["active_runs"] == 1
    assert overview["failed_items"] == 3
    assert overview["failed_jobs"] == 2
    assert failed_job_scan_calls == [True]
