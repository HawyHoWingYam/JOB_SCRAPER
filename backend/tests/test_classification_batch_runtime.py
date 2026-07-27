from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

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
    ClassificationBatchRuntime,
    ClassificationCandidate,
)
from app.services.classification_domain_adapters import (
    SkillClassificationAdapter,
    SkillPlacementDecision,
)
from app.api.classification_batches import router as classification_batch_router


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


def test_skill_auto_create_threshold_defaults_to_five_and_is_configurable():
    engine = create_engine("sqlite:///:memory:")
    AppRuntimeSettings.__table__.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        settings = AIRuntimeSettingsService(db)
        assert settings.get_skill_auto_create_distinct_job_threshold() == 5

        settings.update_settings({"skill_auto_create_distinct_job_threshold": 8})
        assert settings.get_skill_auto_create_distinct_job_threshold() == 8
        assert settings.serialize_persisted_config()[
            "skill_auto_create_distinct_job_threshold"
        ] == 8

        with pytest.raises(RuntimeSettingsValidationError):
            settings.update_settings({"skill_auto_create_distinct_job_threshold": 0})
    finally:
        db.close()
        engine.dispose()


class _PlacementClassifier:
    def __init__(self, decision: SkillPlacementDecision):
        self.decision = decision

    async def classify(self, **_kwargs) -> SkillPlacementDecision:
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
            db, name="Eligible", normalized_key="eligible", distinct_jobs=5
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
            db, name="Py", normalized_key="py", distinct_jobs=5
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
        ) == 5
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
            db, name="DuckDB", normalized_key="duckdb", distinct_jobs=5
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

        await adapter.process_candidate(
            db,
            ClassificationCandidate(subject_id=str(candidate.id), payload={}),
        )
        db.commit()

        created = db.get(CurrentTaxonomyNodeRecord, ("skill", "data.warehouse.duckdb"))
        assert created is not None
        assert created.parent_code == "data.warehouse"
        assert created.is_assignable is True
        db.refresh(candidate)
        assert candidate.resolved_skill_code == "data.warehouse.duckdb"
    finally:
        _close_skill_db(db)


@pytest.mark.asyncio
async def test_skill_adapter_leaves_uncertain_placement_failed_without_fallback():
    db = _skill_db()
    try:
        candidate = _add_skill_candidate(
            db, name="MysteryDB", normalized_key="mysterydb", distinct_jobs=5
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
            distinct_jobs=5,
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
