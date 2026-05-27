from __future__ import annotations

from uuid import uuid4

from app.models.company import Company
from app.models.company_enrichment_run import CompanyEnrichmentRun, CompanyEnrichmentRunItem
from app.services.company_enrichment_run_service import CompanyEnrichmentRunService


class _FakeQuery:
    def __init__(self, *, all_result=None):
        self.all_result = list(all_result or [])

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.all_result)


class _FakeDB:
    def __init__(self, queries):
        self._queries = list(queries)
        self.query_calls = []
        self.added = []

    def query(self, *entities):
        self.query_calls.append(entities)
        if not self._queries:
            raise AssertionError("Unexpected query call")
        return self._queries.pop(0)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for obj in self.added:
            if isinstance(obj, CompanyEnrichmentRun) and not getattr(obj, "id", None):
                obj.id = "run-1"


def test_create_pending_run_queries_pending_company_ids_only():
    company_id_a = uuid4()
    company_id_b = uuid4()
    db = _FakeDB([
        _FakeQuery(all_result=[(company_id_a,), (company_id_b,)]),
    ])
    service = CompanyEnrichmentRunService(db)

    run = service.create_pending_run()

    assert db.query_calls[0] == (Company.id,)
    assert run is not None
    assert run.total_items == 2
    assert run.pending_items == 2

    items = [obj for obj in db.added if isinstance(obj, CompanyEnrichmentRunItem)]
    assert [item.company_id for item in items] == [company_id_a, company_id_b]


def test_create_pending_run_with_force_company_ids_queries_ids_only_and_preserves_requested_order():
    company_id_a = uuid4()
    company_id_b = uuid4()
    db = _FakeDB([
        _FakeQuery(all_result=[(company_id_a,), (company_id_b,)]),
    ])
    service = CompanyEnrichmentRunService(db)

    run = service.create_pending_run(force_company_ids=[str(company_id_b), str(company_id_a)])

    assert db.query_calls[0] == (Company.id,)
    assert run is not None
    items = [obj for obj in db.added if isinstance(obj, CompanyEnrichmentRunItem)]
    assert [item.company_id for item in items] == [company_id_b, company_id_a]
