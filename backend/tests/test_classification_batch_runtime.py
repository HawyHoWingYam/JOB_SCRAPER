from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.main as app_main
from app.api.classification_batches import router as classification_batch_router
from app.models.classification_batch import (
    ClassificationBatchRun,
    ClassificationBatchRunItem,
)
from app.models.app_runtime_settings import AppRuntimeSettings
from app.models.current_taxonomy import (
    CurrentJobSkillAssignment,
    CurrentJobSkillMention,
    CurrentSkillCandidate,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)
from app.services.ai_runtime_settings_service import (
    AIRuntimeSettingsService,
    RuntimeSettingsValidationError,
)
from app.services.classification_batch_runtime import (
    ClassificationBatchError,
    ClassificationBatchRuntime,
    ClassificationCandidate,
)
from app.services.classification_domain_adapters import (
    SkillClassificationAdapter,
    SkillPlacementDecision,
)
from app.services.skill_taxonomy_bootstrap import (
    reconcile_deterministic_skill_candidates,
    synchronize_initial_skill_taxonomy,
)
@dataclass
class _FakeAdapter:
    domain: str = "skill"

    def select_candidates(
        self,
        db: Session,
        *,
        filters: dict[str, object],
        limit: int,
    ) -> tuple[ClassificationCandidate, ...]:
        del db, filters
        return tuple(
            ClassificationCandidate(
                subject_id=value,
                subject_label=f"Candidate {value}",
                payload={"value": value},
            )
            for value in ("one", "two", "three")[:limit]
        )

    async def process_candidate(
        self,
        db: Session,
        candidate: ClassificationCandidate,
    ) -> None:
        del db
        if candidate.subject_id == "two":
            raise ValueError("placement uncertain")


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    ClassificationBatchRun.__table__.create(engine)
    ClassificationBatchRunItem.__table__.create(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_batch_public_lifecycle_previews_runs_and_retries_failures(db: Session):
    runtime = ClassificationBatchRuntime(db, {"skill": _FakeAdapter()})

    preview = runtime.preview("skill", filters={}, limit=2)
    assert preview.selected_item_count == 2
    assert [item.subject_id for item in preview.items] == ["one", "two"]

    run = runtime.start("skill", filters={}, limit=2)
    assert run.status == "pending"
    assert run.total_items == 2

    await runtime.execute(run.id)
    db.refresh(run)
    assert run.status == "completed_with_failures"
    assert run.completed_items == 1
    assert run.failed_items == 1

    failed = db.scalar(
        select(ClassificationBatchRunItem).where(
            ClassificationBatchRunItem.run_id == run.id,
            ClassificationBatchRunItem.status == "failed",
        )
    )
    assert failed is not None
    assert failed.subject_id == "two"
    assert failed.error_code == "ValueError"
    assert failed.error_message == "placement uncertain"

    retry = runtime.retry_failed(run.id)
    assert retry.status == "pending"
    assert retry.total_items == 1
    assert retry.retry_of_run_id == run.id


def test_stop_cancels_a_pending_batch_without_processing_items(db: Session):
    runtime = ClassificationBatchRuntime(db, {"skill": _FakeAdapter()})
    run = runtime.start("skill", filters={}, limit=3)

    stopped = runtime.request_stop(run.id)

    assert stopped.status == "cancelled"
    assert stopped.cancelled_items == 3
    assert stopped.pending_items == 0
    assert {
        item.status
        for item in db.scalars(
            select(ClassificationBatchRunItem).where(
                ClassificationBatchRunItem.run_id == run.id
            )
        )
    } == {"cancelled"}


@pytest.mark.asyncio
async def test_stop_on_a_running_batch_finishes_cooperatively(db: Session):
    runtime = ClassificationBatchRuntime(db, {"skill": _FakeAdapter()})
    run = runtime.start("skill", filters={}, limit=3)
    run.status = "running"
    db.commit()

    stopping = runtime.request_stop(run.id)
    assert stopping.status == "stopping"

    finished = await runtime.execute(run.id)
    assert finished.status == "cancelled"
    assert finished.cancelled_items == 3


def test_skill_auto_create_threshold_defaults_to_ten_and_is_configurable():
    engine = create_engine("sqlite:///:memory:")
    AppRuntimeSettings.__table__.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        settings = AIRuntimeSettingsService(db)
        assert settings.get_skill_auto_create_distinct_job_threshold() == 10
        assert settings.get_skill_candidate_recommendation_limit() == 5
        assert settings.get_skill_candidate_evidence_limit() == 5

        settings.update_settings({"skill_auto_create_distinct_job_threshold": 8})
        assert settings.get_skill_auto_create_distinct_job_threshold() == 8
        assert settings.serialize_persisted_config()[
            "skill_auto_create_distinct_job_threshold"
        ] == 8

        settings.update_settings({
            "skill_candidate_recommendation_limit": 7,
            "skill_candidate_evidence_limit": 6,
        })
        assert settings.get_skill_candidate_recommendation_limit() == 7
        assert settings.get_skill_candidate_evidence_limit() == 6

        with pytest.raises(RuntimeSettingsValidationError):
            settings.update_settings({"skill_auto_create_distinct_job_threshold": 0})
        with pytest.raises(RuntimeSettingsValidationError):
            settings.update_settings({"skill_candidate_recommendation_limit": 0})
    finally:
        db.close()
        engine.dispose()


def test_skill_taxonomy_startup_reconciles_even_when_taxonomy_already_exists(monkeypatch):
    """Historical deterministic candidates must not depend on the seed flag."""

    class _Session:
        def __init__(self):
            self.committed = False
            self.closed = False

        def commit(self):
            self.committed = True

        def close(self):
            self.closed = True

    session = _Session()
    calls: list[object] = []
    monkeypatch.setattr(app_main, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        app_main,
        "synchronize_initial_skill_taxonomy",
        lambda db: {"seeded": False, "nodes": 0, "aliases": 0},
    )
    monkeypatch.setattr(
        app_main,
        "reconcile_deterministic_skill_candidates",
        lambda db: calls.append(db) or 2,
    )

    result = app_main.synchronize_skill_taxonomy_on_startup()

    assert result["deterministically_reconciled"] == 2
    assert calls == [session]
    assert session.committed is True
    assert session.closed is True


def test_skill_taxonomy_manifest_covers_cpp_as_a_governed_backend_skill():
    db = _skill_db()
    try:
        summary = synchronize_initial_skill_taxonomy(db)
        cpp = db.get(CurrentTaxonomyNodeRecord, ("skill", "backend.c-plus-plus.c-plus-plus"))
        technology = db.get(CurrentTaxonomyNodeRecord, ("skill", "backend.c-plus-plus"))
        assert summary["seeded"] is True
        assert cpp is not None and cpp.is_assignable is True
        assert technology is not None and technology.level == "technology"
        assert cpp.parent_code == technology.code
    finally:
        _close_skill_db(db)


def test_deterministic_reconciliation_resolves_historical_exact_skill_idempotently():
    db = _skill_db()
    try:
        db.add(
            CurrentTaxonomyNodeRecord(
                taxonomy="skill",
                code="database.sql.sql",
                parent_code="database.sql",
                level="skill",
                labels={"en": "SQL"},
                sort_order=0,
                is_assignable=True,
                is_active=True,
            )
        )
        db.add(
            CurrentTaxonomyNodeRecord(
                taxonomy="skill",
                code="database.sql",
                parent_code=None,
                level="technology",
                labels={"en": "SQL"},
                sort_order=0,
                is_assignable=False,
                is_active=True,
            )
        )
        db.flush()
        candidate = _add_skill_candidate(
            db, name="SQL", normalized_key="sql", distinct_jobs=10
        )

        assert reconcile_deterministic_skill_candidates(db) == 1
        db.commit()
        db.refresh(candidate)
        assert candidate.resolved_skill_code == "database.sql.sql"
        assert reconcile_deterministic_skill_candidates(db) == 0
    finally:
        _close_skill_db(db)


class _PlacementClassifier:
    def __init__(self, decision: SkillPlacementDecision):
        self.decision = decision
        self.calls = 0

    async def classify(self, **_kwargs) -> SkillPlacementDecision:
        self.calls += 1
        return self.decision


def _skill_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    for table in (
        AppRuntimeSettings.__table__,
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
        CurrentSkillCandidate.__table__,
        CurrentJobSkillMention.__table__,
        CurrentJobSkillAssignment.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    db.info["test_engine"] = engine
    return db


def _add_skill_candidate(
    db: Session,
    *,
    name: str,
    normalized_key: str,
    distinct_jobs: int,
) -> CurrentSkillCandidate:
    candidate = CurrentSkillCandidate(
        normalized_key=normalized_key,
        canonical_raw_name=name,
        raw_variants=[name],
        occurrence_count=distinct_jobs,
        distinct_job_count=distinct_jobs,
        evidence_summary={},
    )
    db.add(candidate)
    db.flush()
    for _ in range(distinct_jobs):
        db.add(
            CurrentJobSkillMention(
                job_id=uuid4(),
                raw_name=name,
                normalized_key=normalized_key,
                resolution="candidate",
                status="active",
                candidate_id=candidate.id,
                source="test",
                provenance={},
                evidence_hash=uuid4().hex,
            )
        )
    db.commit()
    return candidate


def _close_skill_db(db: Session) -> None:
    engine = db.info["test_engine"]
    db.close()
    engine.dispose()


def test_skill_adapter_selects_only_candidates_at_the_current_distinct_job_threshold():
    db = _skill_db()
    try:
        below = _add_skill_candidate(
            db, name="Below", normalized_key="below", distinct_jobs=4
        )
        eligible = _add_skill_candidate(
            db, name="Eligible", normalized_key="eligible", distinct_jobs=10
        )
        adapter = SkillClassificationAdapter(
            placement_classifier=_PlacementClassifier(
                SkillPlacementDecision(status="uncertain")
            )
        )

        selected = adapter.select_candidates(db, filters={}, limit=10)

        assert [item.subject_id for item in selected] == [str(eligible.id)]
        assert str(below.id) not in {item.subject_id for item in selected}
    finally:
        _close_skill_db(db)


@pytest.mark.asyncio
async def test_skill_adapter_reuses_an_existing_alias_and_reprojects_jobs():
    db = _skill_db()
    try:
        db.add_all(
            [
                CurrentTaxonomyNodeRecord(
                    taxonomy="skill",
                    code="backend",
                    parent_code=None,
                    level="category",
                    labels={"en": "Backend"},
                    sort_order=1,
                    is_assignable=False,
                    is_active=True,
                ),
                CurrentTaxonomyNodeRecord(
                    taxonomy="skill",
                    code="backend.python",
                    parent_code="backend",
                    level="technology",
                    labels={"en": "Python"},
                    sort_order=1,
                    is_assignable=False,
                    is_active=True,
                ),
                CurrentTaxonomyNodeRecord(
                    taxonomy="skill",
                    code="backend.python.python",
                    parent_code="backend.python",
                    level="skill",
                    labels={"en": "Python"},
                    sort_order=1,
                    is_assignable=True,
                    is_active=True,
                ),
                CurrentTaxonomyAliasRecord(
                    taxonomy="skill",
                    node_code="backend.python.python",
                    alias="Py",
                    normalized_alias="py",
                ),
            ]
        )
        db.commit()
        candidate = _add_skill_candidate(
            db, name="Py", normalized_key="py", distinct_jobs=10
        )
        adapter = SkillClassificationAdapter(
            placement_classifier=_PlacementClassifier(
                SkillPlacementDecision(status="uncertain")
            )
        )

        await adapter.process_candidate(
            db,
            ClassificationCandidate(subject_id=str(candidate.id), payload={}),
        )
        db.commit()

        db.refresh(candidate)
        assert candidate.resolved_skill_code == "backend.python.python"
        mentions = tuple(
            db.scalars(
                select(CurrentJobSkillMention).where(
                    CurrentJobSkillMention.origin_candidate_id == candidate.id
                )
            )
        )
        assert {mention.resolution for mention in mentions} == {"match_existing"}
        assert {mention.skill_code for mention in mentions} == {
            "backend.python.python"
        }
        assert db.scalar(
            select(func.count()).select_from(CurrentJobSkillAssignment)
        ) == 10
    finally:
        _close_skill_db(db)


@pytest.mark.asyncio
async def test_skill_adapter_creates_only_under_a_confirmed_existing_technology():
    db = _skill_db()
    try:
        db.add_all(
            [
                CurrentTaxonomyNodeRecord(
                    taxonomy="skill",
                    code="data",
                    parent_code=None,
                    level="category",
                    labels={"en": "Data"},
                    sort_order=1,
                    is_assignable=False,
                    is_active=True,
                ),
                CurrentTaxonomyNodeRecord(
                    taxonomy="skill",
                    code="data.warehouse",
                    parent_code="data",
                    level="technology",
                    labels={"en": "Data Warehouse"},
                    sort_order=1,
                    is_assignable=False,
                    is_active=True,
                ),
            ]
        )
        db.commit()
        candidate = _add_skill_candidate(
            db, name="DuckDB", normalized_key="duckdb", distinct_jobs=10
        )
        adapter = SkillClassificationAdapter(
            placement_classifier=_PlacementClassifier(
                SkillPlacementDecision(
                    status="create",
                    category_code="data",
                    technology_code="data.warehouse",
                    name="DuckDB",
                )
            )
        )

        with pytest.raises(ValueError, match="operator confirmation"):
            await adapter.process_candidate(
                db,
                ClassificationCandidate(subject_id=str(candidate.id), payload={}),
            )
        db.commit()

        created = db.get(CurrentTaxonomyNodeRecord, ("skill", "data.warehouse.duckdb"))
        assert created is None
        db.refresh(candidate)
        assert candidate.resolved_skill_code is None
    finally:
        _close_skill_db(db)


@pytest.mark.asyncio
async def test_skill_adapter_leaves_uncertain_placement_failed_without_fallback():
    db = _skill_db()
    try:
        candidate = _add_skill_candidate(
            db, name="MysteryDB", normalized_key="mysterydb", distinct_jobs=10
        )
        adapter = SkillClassificationAdapter(
            placement_classifier=_PlacementClassifier(
                SkillPlacementDecision(status="uncertain")
            )
        )

        with pytest.raises(ValueError, match="placement is uncertain"):
            await adapter.process_candidate(
                db,
                ClassificationCandidate(subject_id=str(candidate.id), payload={}),
            )

        assert db.get(CurrentTaxonomyNodeRecord, ("skill", "other")) is None
        assert db.get(CurrentTaxonomyNodeRecord, ("skill", "unknown")) is None
    finally:
        _close_skill_db(db)


@pytest.mark.asyncio
async def test_skill_adapter_classifies_a_known_generic_term_without_creating_skill():
    db = _skill_db()
    try:
        candidate = _add_skill_candidate(
            db,
            name="Project Management",
            normalized_key="project management",
            distinct_jobs=10,
        )
        adapter = SkillClassificationAdapter(
            placement_classifier=_PlacementClassifier(
                SkillPlacementDecision(
                    status="create",
                    category_code="missing",
                    technology_code="missing",
                )
            )
        )

        await adapter.process_candidate(
            db,
            ClassificationCandidate(subject_id=str(candidate.id), payload={}),
        )
        db.commit()

        mentions = tuple(
            db.scalars(
                select(CurrentJobSkillMention).where(
                    CurrentJobSkillMention.origin_candidate_id == candidate.id
                )
            )
        )
        assert {mention.resolution for mention in mentions} == {"generic_tag"}
        assert db.scalar(
            select(func.count()).select_from(CurrentTaxonomyNodeRecord)
        ) == 0
    finally:
        _close_skill_db(db)


@pytest.mark.parametrize(
    ("raw_name", "generic_tag"),
    (
        ("項目管理", "Project Management"),
        ("銷售", "Sales"),
        ("客戶服務", "Customer Service"),
    ),
)
@pytest.mark.asyncio
async def test_skill_adapter_resolves_localized_generic_aliases_without_llm(
    raw_name: str,
    generic_tag: str,
):
    db = _skill_db()
    try:
        candidate = _add_skill_candidate(
            db,
            name=raw_name,
            normalized_key=raw_name,
            distinct_jobs=10,
        )
        classifier = _PlacementClassifier(SkillPlacementDecision(status="uncertain"))
        adapter = SkillClassificationAdapter(placement_classifier=classifier)

        await adapter.process_candidate(
            db,
            ClassificationCandidate(subject_id=str(candidate.id), payload={}),
        )
        db.commit()

        mentions = tuple(
            db.scalars(
                select(CurrentJobSkillMention).where(
                    CurrentJobSkillMention.origin_candidate_id == candidate.id
                )
            )
        )
        assert classifier.calls == 0
        assert {mention.raw_name for mention in mentions} == {raw_name}
        assert {mention.resolution for mention in mentions} == {"generic_tag"}
        assert {mention.generic_tag for mention in mentions} == {generic_tag}
        assert {mention.candidate_id for mention in mentions} == {None}
        db.refresh(candidate)
        assert candidate.occurrence_count == 0
        assert candidate.distinct_job_count == 0
        assert adapter.select_candidates(db, filters={}, limit=10) == ()
        assert db.scalar(select(func.count()).select_from(CurrentJobSkillAssignment)) == 0
        assert db.scalar(select(func.count()).select_from(CurrentTaxonomyNodeRecord)) == 0
    finally:
        _close_skill_db(db)


@pytest.mark.asyncio
async def test_retry_excludes_a_skill_candidate_resolved_after_the_source_run_failed():
    db = _skill_db()
    try:
        engine = db.info["test_engine"]
        ClassificationBatchRun.__table__.create(engine)
        ClassificationBatchRunItem.__table__.create(engine)
        candidate = _add_skill_candidate(
            db,
            name="項目管理",
            normalized_key="項目管理",
            distinct_jobs=10,
        )
        source_run = ClassificationBatchRun(
            domain="skill",
            status="failed",
            filters={},
            requested_limit=1,
            total_items=1,
            pending_items=0,
            completed_items=0,
            failed_items=1,
            cancelled_items=0,
        )
        db.add(source_run)
        db.flush()
        db.add(
            ClassificationBatchRunItem(
                run_id=source_run.id,
                subject_id=str(candidate.id),
                subject_label=candidate.canonical_raw_name,
                position=0,
                payload={},
                status="failed",
                attempt_count=1,
                error_code="ValueError",
                error_message="Skill candidate placement is uncertain",
            )
        )
        db.commit()
        adapter = SkillClassificationAdapter(
            placement_classifier=_PlacementClassifier(
                SkillPlacementDecision(status="uncertain")
            )
        )
        await adapter.process_candidate(
            db,
            ClassificationCandidate(subject_id=str(candidate.id), payload={}),
        )
        db.commit()
        runtime = ClassificationBatchRuntime(db, {"skill": adapter})

        with pytest.raises(
            ClassificationBatchError,
            match="no failed items that remain retryable",
        ):
            runtime.retry_failed(source_run.id)

        assert db.scalar(select(func.count()).select_from(ClassificationBatchRun)) == 1
    finally:
        _close_skill_db(db)


def test_classification_batch_api_exposes_one_shared_lifecycle_for_all_domains():
    paths = {route.path for route in classification_batch_router.routes}

    assert paths == {
        "/job-intelligence/classification-batches/{domain}/preview",
        "/job-intelligence/classification-batches/{domain}/runs",
        "/job-intelligence/classification-batches/runs",
        "/job-intelligence/classification-batches/runs/{run_id}",
        "/job-intelligence/classification-batches/runs/{run_id}/stop",
        "/job-intelligence/classification-batches/runs/{run_id}/retry-failed",
    }
    assert all("governance" not in path for path in paths)
    assert all("/reviews" not in path for path in paths)
