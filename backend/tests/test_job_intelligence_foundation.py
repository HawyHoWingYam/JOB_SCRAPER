from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import ast
import runpy
import sys
from types import ModuleType, SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.job_intelligence.foundation import (
    AuditEvent,
    AuditPage,
    AuditQuery,
    AuditReader,
    DecisionCommand,
    DecisionContractError,
    DecisionEffect,
    GovernanceUnitOfWork,
    IdempotencyConflictError,
    InvalidDecisionActorError,
    OutboxEvent,
    Provenance,
    RevisionConflictError,
    RevisionRef,
    RevisionManifest,
    RevisionStore,
    SeedIssue,
    SeedValidator,
    StaleDecisionVersionError,
    UnconfirmedDecisionError,
    normalized_content_hash,
)
from app.models.event_outbox import EventOutbox
from app.models.governance import GOVERNANCE_FOUNDATION_TABLES
from app.models.governance import GovernanceRevision
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.schemas.job_intelligence import GovernanceAuditPageSchema


class FakeGovernanceSubject(Base):
    __tablename__ = "test_governance_subjects"

    id = Column(String(100), primary_key=True)
    domain = Column(String(100), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    target_id = Column(String(100), nullable=True)
    lock_version = Column(Integer, nullable=False, default=1)


class _AssignExistingTarget:
    def __init__(self, *, domain: str, subject_type: str) -> None:
        self.domain = domain
        self.subject_type = subject_type

    def load_for_update(self, db, subject_id):
        return (
            db.query(FakeGovernanceSubject)
            .filter(
                FakeGovernanceSubject.id == subject_id,
                FakeGovernanceSubject.domain == self.domain,
            )
            .with_for_update()
            .one_or_none()
        )

    def version(self, subject):
        return subject.lock_version

    def snapshot(self, subject):
        return {
            "id": subject.id,
            "status": subject.status,
            "target_id": subject.target_id,
            "version": subject.lock_version,
        }

    def apply(self, _db, subject, command):
        subject.status = "assigned"
        subject.target_id = command.target_id
        subject.lock_version += 1
        return DecisionEffect(
            subject=self.snapshot(subject),
            resulting_projection={
                "subject_id": subject.id,
                "target_id": subject.target_id,
            },
            version=subject.lock_version,
            evidence_refs=({"kind": "fixture", "id": subject.id},),
            outbox_events=(
                OutboxEvent(
                    topic="job-intelligence-projections",
                    aggregate_type=self.subject_type,
                    aggregate_id=subject.id,
                    event_type=f"{self.domain}.decision-applied",
                    payload={"subject_id": subject.id},
                ),
            ),
        )


class _InvalidOutboxPayload(_AssignExistingTarget):
    def apply(self, db, subject, command):
        effect = super().apply(db, subject, command)
        return DecisionEffect(
            subject=effect.subject,
            resulting_projection=effect.resulting_projection,
            version=effect.version,
            evidence_refs=effect.evidence_refs,
            outbox_events=(
                OutboxEvent(
                    topic="job-intelligence-projections",
                    aggregate_type=self.subject_type,
                    aggregate_id=subject.id,
                    event_type=f"{self.domain}.decision-applied",
                    payload={"not_json": object()},
                ),
            ),
        )


class _MissingOutboxEvent(_AssignExistingTarget):
    def apply(self, db, subject, command):
        effect = super().apply(db, subject, command)
        return DecisionEffect(
            subject=effect.subject,
            resulting_projection=effect.resulting_projection,
            version=effect.version,
            evidence_refs=effect.evidence_refs,
            outbox_events=(),
        )


@pytest.fixture()
def foundation_db():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")
    engine = create_engine(database_url)
    tables = (
        *GOVERNANCE_FOUNDATION_TABLES,
        EventOutbox.__table__,
        FakeGovernanceSubject.__table__,
    )
    Base.metadata.create_all(engine, tables=tables)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(
            engine,
            tables=list(reversed(tables)),
        )
        engine.dispose()


def test_normalized_content_hash_is_independent_of_mapping_order():
    first = {"z": 1, "a": [3, 2, 1]}
    second = {"a": [3, 2, 1], "z": 1}

    assert normalized_content_hash(first) == normalized_content_hash(second)
    assert (
        normalized_content_hash(first)
        == "317f7ae9e3098f1b542ecc1a158a50d46d4e5c2fb63753274e0f9c2a4a221f90"
    )


def test_provenance_keeps_typed_source_mapping_model_and_evidence_references():
    provenance = Provenance(
        method="constrained-ai-selection",
        source_site="jobsdb",
        source_revision=RevisionRef(
            domain="source-catalog",
            revision_id=UUID("00000000-0000-0000-0000-000000000123"),
            release_key="jobsdb-42",
            content_hash="a" * 64,
        ),
        mapping_id="mapping-7",
        evidence_refs=({"kind": "raw-job", "id": "job-1"},),
        model_provider="google",
        model_name="gemini",
        model_version="2.5",
        captured_at=datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc),
    )

    assert provenance.to_payload() == {
        "method": "constrained-ai-selection",
        "source_site": "jobsdb",
        "source_revision": {
            "domain": "source-catalog",
            "revision_id": "00000000-0000-0000-0000-000000000123",
            "release_key": "jobsdb-42",
            "content_hash": "a" * 64,
        },
        "mapping_id": "mapping-7",
        "evidence_refs": [{"kind": "raw-job", "id": "job-1"}],
        "model_provider": "google",
        "model_name": "gemini",
        "model_version": "2.5",
        "captured_at": "2026-07-18T12:00:00+00:00",
    }


def test_seed_validator_reports_every_issue_in_deterministic_order():
    def missing_parent(_document):
        return (
            SeedIssue(
                json_path="$.nodes[2].parent",
                code="MISSING_REFERENCE",
                message="Parent code does not exist",
                related_id="missing-parent",
            ),
        )

    def duplicate_codes(_document):
        return (
            SeedIssue(
                json_path="$.nodes[1].code",
                code="DUPLICATE_CODE",
                message="Code must be unique",
                related_id="software",
            ),
            SeedIssue(
                json_path="$.nodes[0].code",
                code="DUPLICATE_CODE",
                message="Code must be unique",
                related_id="software",
            ),
        )

    report = SeedValidator.validate(
        {"nodes": []},
        rules=(missing_parent, duplicate_codes),
    )

    assert report.valid is False
    assert [
        (issue.json_path, issue.code, issue.related_id) for issue in report.issues
    ] == [
        ("$.nodes[0].code", "DUPLICATE_CODE", "software"),
        ("$.nodes[1].code", "DUPLICATE_CODE", "software"),
        ("$.nodes[2].parent", "MISSING_REFERENCE", "missing-parent"),
    ]


def test_revision_store_replays_an_exact_content_addressed_publication(
    foundation_db,
):
    manifest = RevisionManifest.from_content(
        domain="skill-taxonomy",
        release_key="skills-2026-07-18",
        content={"nodes": [{"code": "python"}]},
        source_metadata={"authority": "project"},
    )
    store = RevisionStore(foundation_db)

    first = store.publish(manifest)
    replay = store.publish(manifest)

    assert replay == first
    assert replay.domain == "skill-taxonomy"
    assert replay.release_key == "skills-2026-07-18"
    assert replay.content_hash == normalized_content_hash(
        {"nodes": [{"code": "python"}]}
    )


def test_revision_store_rejects_rebinding_and_model_updates(foundation_db):
    store = RevisionStore(foundation_db)
    first = store.publish(
        RevisionManifest.from_content(
            domain="company-industry",
            release_key="hsic-v2",
            content={"nodes": [{"code": "J"}]},
        )
    )

    with pytest.raises(RevisionConflictError):
        store.publish(
            RevisionManifest.from_content(
                domain="company-industry",
                release_key="hsic-v2",
                content={"nodes": [{"code": "K"}]},
            )
        )

    row = foundation_db.get(GovernanceRevision, first.revision_id)
    row.release_key = "mutated"
    with pytest.raises(ValueError, match="immutable"):
        foundation_db.commit()
    foundation_db.rollback()


def test_revision_store_reports_stable_conflict_when_key_and_hash_match_two_rows(
    foundation_db,
):
    store = RevisionStore(foundation_db)
    store.publish(
        RevisionManifest.from_content(
            domain="skill-taxonomy",
            release_key="skills-v1",
            content={"nodes": [{"code": "python"}]},
        )
    )
    second = RevisionManifest.from_content(
        domain="skill-taxonomy",
        release_key="skills-v2",
        content={"nodes": [{"code": "java"}]},
    )
    store.publish(second)

    with pytest.raises(RevisionConflictError):
        store.publish(
            RevisionManifest(
                domain="skill-taxonomy",
                release_key="skills-v1",
                content_hash=second.content_hash,
            )
        )


def test_concurrent_revision_publication_returns_one_revision(foundation_db):
    manifest = RevisionManifest.from_content(
        domain="canonical-job-taxonomy",
        release_key="taxonomy-2026-07-18",
        content={"domains": [{"code": "technology"}]},
    )
    session_factory = sessionmaker(bind=foundation_db.get_bind())

    def publish():
        db = session_factory()
        try:
            return RevisionStore(db).publish(manifest)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        refs = list(executor.map(lambda _index: publish(), range(2)))

    assert refs[0] == refs[1]


@pytest.mark.parametrize(
    ("domain", "subject_type"),
    (
        ("job-taxonomy", "job-taxonomy-review-item"),
        ("skill-governance", "skill-candidate"),
    ),
)
def test_governance_unit_of_work_applies_two_domain_adapters_atomically(
    foundation_db,
    domain,
    subject_type,
):
    subject = FakeGovernanceSubject(
        id=f"{domain}-1",
        domain=domain,
        status="pending",
        lock_version=1,
    )
    foundation_db.add(subject)
    foundation_db.commit()
    transition = _AssignExistingTarget(
        domain=domain,
        subject_type=subject_type,
    )

    result = GovernanceUnitOfWork(foundation_db).execute(
        DecisionCommand(
            subject_id=subject.id,
            action="assign-existing",
            target_id="target-1",
            expected_version=1,
            idempotency_key=f"{domain}-decision-1",
            confirmed=True,
        ),
        transition,
    )

    refreshed = transition.load_for_update(foundation_db, subject.id)
    pending_events = EventOutboxRepository().list_pending(foundation_db)
    assert result.subject == {
        "id": subject.id,
        "status": "assigned",
        "target_id": "target-1",
        "version": 2,
    }
    assert result.version == 2
    assert result.replayed is False
    assert transition.snapshot(refreshed) == result.subject
    assert [event.event_type for event in pending_events] == [
        f"{domain}.decision-applied"
    ]
    assert pending_events[0].payload["governance_audit_event_id"] == str(
        result.audit_event_id
    )


def test_audit_reader_uses_stable_created_at_and_id_cursor_pagination(
    foundation_db,
):
    transition = _AssignExistingTarget(
        domain="job-taxonomy",
        subject_type="job-taxonomy-review-item",
    )
    for index in range(3):
        subject = FakeGovernanceSubject(
            id=f"review-{index}",
            domain=transition.domain,
            status="pending",
            lock_version=1,
        )
        foundation_db.add(subject)
        foundation_db.commit()
        GovernanceUnitOfWork(foundation_db).execute(
            DecisionCommand(
                subject_id=subject.id,
                action="assign-existing",
                target_id=f"target-{index}",
                expected_version=1,
                idempotency_key=f"audit-page-{index}",
                confirmed=True,
            ),
            transition,
        )

    reader = AuditReader(foundation_db)
    first = reader.list(AuditQuery(domain="job-taxonomy", limit=2))
    second = reader.list(
        AuditQuery(
            domain="job-taxonomy",
            limit=2,
            cursor=first.next_cursor,
        )
    )

    assert [event.subject_id for event in first.items] == ["review-2", "review-1"]
    assert first.next_cursor is not None
    assert [event.subject_id for event in second.items] == ["review-0"]
    assert second.next_cursor is None
    assert {event.actor for event in (*first.items, *second.items)} == {
        "local-operator"
    }


def test_audit_page_response_schema_serializes_the_shared_contract():
    page = AuditPage(
        items=(
            AuditEvent(
                id=UUID("00000000-0000-0000-0000-000000000321"),
                domain="skill-governance",
                subject_type="skill-candidate",
                subject_id="candidate-1",
                action="merge",
                actor="local-operator",
                command_hash="c" * 64,
                idempotency_key="decision-321",
                before_summary={"status": "pending"},
                after_summary={"status": "merged"},
                evidence_refs=({"kind": "skill-mention", "id": "mention-1"},),
                correlation_id="decision-321",
                created_at=datetime(2026, 7, 18, 13, 0, tzinfo=timezone.utc),
            ),
        ),
        next_cursor="next-page",
    )

    payload = GovernanceAuditPageSchema.from_contract(page).model_dump(mode="json")

    assert payload["items"][0]["actor"] == "local-operator"
    assert payload["items"][0]["evidence_refs"] == [
        {"kind": "skill-mention", "id": "mention-1"}
    ]
    assert payload["next_cursor"] == "next-page"


def test_audit_reader_rejects_a_malformed_cursor_with_a_stable_error(foundation_db):
    with pytest.raises(ValueError, match="Invalid governance audit cursor"):
        AuditReader(foundation_db).list(
            AuditQuery(domain="skill-governance", cursor="not-a-cursor")
        )


def test_exact_decision_replay_returns_first_result_and_conflicting_reuse_fails(
    foundation_db,
):
    subject = FakeGovernanceSubject(
        id="skill-candidate-1",
        domain="skill-governance",
        status="pending",
        lock_version=1,
    )
    foundation_db.add(subject)
    foundation_db.commit()
    transition = _AssignExistingTarget(
        domain="skill-governance",
        subject_type="skill-candidate",
    )
    command = DecisionCommand(
        subject_id=subject.id,
        action="merge",
        target_id="skill-python",
        expected_version=1,
        idempotency_key="skill-decision-replay",
        confirmed=True,
    )

    first = GovernanceUnitOfWork(foundation_db).execute(command, transition)
    replay = GovernanceUnitOfWork(foundation_db).execute(command, transition)

    assert replay.audit_event_id == first.audit_event_id
    assert replay.subject == first.subject
    assert replay.replayed is True
    assert len(EventOutboxRepository().list_pending(foundation_db)) == 1
    assert (
        len(
            AuditReader(foundation_db).list(AuditQuery(domain="skill-governance")).items
        )
        == 1
    )

    with pytest.raises(IdempotencyConflictError):
        GovernanceUnitOfWork(foundation_db).execute(
            DecisionCommand(
                subject_id=subject.id,
                action="merge",
                target_id="skill-java",
                expected_version=1,
                idempotency_key="skill-decision-replay",
                confirmed=True,
            ),
            transition,
        )


@pytest.mark.parametrize(
    ("overrides", "error_type"),
    (
        ({"confirmed": False}, UnconfirmedDecisionError),
        ({"actor": "worker"}, InvalidDecisionActorError),
        ({"expected_version": 0}, StaleDecisionVersionError),
    ),
)
def test_rejected_decisions_leave_no_effect_audit_or_outbox(
    foundation_db,
    overrides,
    error_type,
):
    subject = FakeGovernanceSubject(
        id="company-industry-review-1",
        domain="company-industry",
        status="pending",
        lock_version=1,
    )
    foundation_db.add(subject)
    foundation_db.commit()
    transition = _AssignExistingTarget(
        domain="company-industry",
        subject_type="company-industry-review-item",
    )
    command_fields = {
        "subject_id": subject.id,
        "action": "assign-existing",
        "target_id": "hsic-62010",
        "expected_version": 1,
        "idempotency_key": f"rejected-{error_type.__name__}",
        "confirmed": True,
        **overrides,
    }

    with pytest.raises(error_type):
        GovernanceUnitOfWork(foundation_db).execute(
            DecisionCommand(**command_fields),
            transition,
        )

    foundation_db.refresh(subject)
    assert transition.snapshot(subject) == {
        "id": subject.id,
        "status": "pending",
        "target_id": None,
        "version": 1,
    }
    assert EventOutboxRepository().list_pending(foundation_db) == []
    assert (
        AuditReader(foundation_db).list(AuditQuery(domain="company-industry")).items
        == ()
    )


def test_outbox_serialization_failure_rolls_back_effect_audit_and_idempotency(
    foundation_db,
):
    subject = FakeGovernanceSubject(
        id="job-review-rollback",
        domain="job-taxonomy",
        status="pending",
        lock_version=1,
    )
    foundation_db.add(subject)
    foundation_db.commit()
    command = DecisionCommand(
        subject_id=subject.id,
        action="assign-existing",
        target_id="subcategory-python",
        expected_version=1,
        idempotency_key="rollback-after-audit",
        confirmed=True,
    )
    failing_transition = _InvalidOutboxPayload(
        domain="job-taxonomy",
        subject_type="job-taxonomy-review-item",
    )

    with pytest.raises(TypeError, match="non-JSON"):
        GovernanceUnitOfWork(foundation_db).execute(command, failing_transition)

    foundation_db.refresh(subject)
    assert failing_transition.snapshot(subject)["status"] == "pending"
    assert EventOutboxRepository().list_pending(foundation_db) == []
    assert (
        AuditReader(foundation_db).list(AuditQuery(domain="job-taxonomy")).items == ()
    )

    retry = GovernanceUnitOfWork(foundation_db).execute(
        command,
        _AssignExistingTarget(
            domain="job-taxonomy",
            subject_type="job-taxonomy-review-item",
        ),
    )
    assert retry.replayed is False


def test_decision_without_outbox_event_is_rejected_and_rolled_back(foundation_db):
    subject = FakeGovernanceSubject(
        id="company-review-without-outbox",
        domain="company-industry",
        status="pending",
        lock_version=1,
    )
    foundation_db.add(subject)
    foundation_db.commit()

    with pytest.raises(DecisionContractError, match="outbox"):
        GovernanceUnitOfWork(foundation_db).execute(
            DecisionCommand(
                subject_id=subject.id,
                action="assign-existing",
                target_id="hsic-62010",
                expected_version=1,
                idempotency_key="missing-outbox",
                confirmed=True,
            ),
            _MissingOutboxEvent(
                domain="company-industry",
                subject_type="company-industry-review-item",
            ),
        )

    foundation_db.refresh(subject)
    assert subject.status == "pending"


def test_concurrent_exact_decisions_commit_once_and_replay_once(foundation_db):
    subject = FakeGovernanceSubject(
        id="concurrent-skill-candidate",
        domain="skill-governance",
        status="pending",
        lock_version=1,
    )
    foundation_db.add(subject)
    foundation_db.commit()
    command = DecisionCommand(
        subject_id=subject.id,
        action="merge",
        target_id="skill-python",
        expected_version=1,
        idempotency_key="concurrent-skill-decision",
        confirmed=True,
    )
    session_factory = sessionmaker(bind=foundation_db.get_bind())

    def execute():
        db = session_factory()
        try:
            return GovernanceUnitOfWork(db).execute(
                command,
                _AssignExistingTarget(
                    domain="skill-governance",
                    subject_type="skill-candidate",
                ),
            )
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: execute(), range(2)))

    foundation_db.expire_all()
    assert sorted(result.replayed for result in results) == [False, True]
    assert results[0].audit_event_id == results[1].audit_event_id
    assert len(EventOutboxRepository().list_pending(foundation_db)) == 1
    assert (
        len(
            AuditReader(foundation_db).list(AuditQuery(domain="skill-governance")).items
        )
        == 1
    )


def test_foundation_migration_is_schema_only_and_installs_immutability_guards(
    monkeypatch,
):
    created_tables = []
    dropped_tables = []
    executed_sql = []
    alembic_stub = ModuleType("alembic")
    alembic_stub.op = SimpleNamespace(
        create_table=lambda name, *_columns, **_kwargs: created_tables.append(name),
        create_index=lambda *_args, **_kwargs: None,
        drop_index=lambda *_args, **_kwargs: None,
        drop_table=lambda name: dropped_tables.append(name),
        execute=lambda statement: executed_sql.append(str(statement)),
    )
    monkeypatch.setitem(sys.modules, "alembic", alembic_stub)

    migration = runpy.run_path(
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260718_210000_add_job_intelligence_foundation.py"
    )
    migration["upgrade"]()
    migration["downgrade"]()

    assert created_tables == [
        "governance_revisions",
        "governance_audit_events",
        "governance_idempotency_records",
    ]
    assert dropped_tables == list(reversed(created_tables))
    assert not any("INSERT" in statement.upper() for statement in executed_sql)
    assert any(
        "TRG_GOVERNANCE_REVISIONS_IMMUTABLE" in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "TRG_GOVERNANCE_AUDIT_EVENTS_APPEND_ONLY" in statement.upper()
        for statement in executed_sql
    )


def test_worker_modules_do_not_import_or_receive_human_decision_interfaces():
    forbidden_names = {
        "DecisionCommand",
        "DecisionTransition",
        "GovernanceUnitOfWork",
        "decision_adapter",
        "decision_executor",
        "governance_unit_of_work",
    }
    violations = []
    worker_root = Path(__file__).parents[1] / "app" / "workers"
    for path in sorted(worker_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = {alias.name for alias in node.names}
                if imported & forbidden_names:
                    violations.append(f"{path.name}:{node.lineno}:import")
            elif isinstance(node, ast.Name) and node.id in forbidden_names:
                violations.append(f"{path.name}:{node.lineno}:{node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in forbidden_names:
                violations.append(f"{path.name}:{node.lineno}:{node.attr}")
            elif isinstance(node, ast.arg) and node.arg in forbidden_names:
                violations.append(f"{path.name}:{node.lineno}:{node.arg}")

    assert violations == []
