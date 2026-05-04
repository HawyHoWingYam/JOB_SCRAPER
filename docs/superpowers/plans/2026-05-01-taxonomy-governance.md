# Taxonomy Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make canonical job taxonomy and controlled skill vocabulary the only business-truth layers while preserving raw AI extraction output for audit and review.

**Architecture:** Tighten online job taxonomy resolution so it always lands on an existing registry-backed path or a deterministic fallback, then split extracted skills into a new raw mention table plus the existing controlled skill hierarchy. Backfill missing taxonomy links, clean polluted `Other / General` skills, rebuild governance counters from fact tables, and migrate API/query behavior toward canonical taxonomy while keeping legacy response compatibility.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy ORM, Alembic, PostgreSQL, pytest

---

## File Structure

**Create**

- `backend/app/models/job_skill_mention.py`
- `backend/app/repositories/job_skill_mention_repository.py`
- `backend/scripts/govern_job_taxonomy.py`
- `backend/tests/test_job_taxonomy_governance.py`
- `backend/tests/test_api_taxonomy_compat.py`
- `backend/alembic/versions/20260501_103000_add_job_skill_mentions.py`
- `backend/alembic/versions/20260501_130000_drop_redundant_taxonomy_indexes.py`

**Modify**

- `backend/app/models/__init__.py`
- `backend/app/services/job_category_normalizer.py`
- `backend/app/services/skill_normalizer.py`
- `backend/app/services/ai_enrichment_service.py`
- `backend/app/api/jobs.py`
- `backend/app/api/stats.py`
- `backend/app/repositories/job_skill_repository.py`
- `backend/scripts/govern_skill_history.py`
- `backend/scripts/verify_migration.py`
- `backend/tests/test_skill_governance.py`
- `backend/tests/test_skill_history_governance.py`

## Task 1: Lock Canonical Job Taxonomy Resolution

**Files:**

- Create: `backend/tests/test_job_taxonomy_governance.py`
- Modify: `backend/app/services/job_category_normalizer.py`
- Modify: `backend/app/services/ai_enrichment_service.py`

- [ ] **Step 1: Write the failing tests**

```python
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import Company, Job, JobCategory, JobDomain, JobSubcategory
from app.services.job_category_normalizer import JobCategoryNormalizer

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"


def _build_sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            JobDomain.__table__,
            JobCategory.__table__,
            JobSubcategory.__table__,
            Job.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _seed_taxonomy(db):
    domain = JobDomain(id=uuid.uuid4(), name="Information & Communication Technology")
    general_category = JobCategory(
        id=uuid.uuid4(),
        domain_id=domain.id,
        name="General",
    )
    software_category = JobCategory(
        id=uuid.uuid4(),
        domain_id=domain.id,
        name="Software Development",
    )
    general = JobSubcategory(
        id=uuid.uuid4(),
        category_id=general_category.id,
        name="General",
    )
    backend = JobSubcategory(
        id=uuid.uuid4(),
        category_id=software_category.id,
        name="Backend Development",
    )
    db.add_all([domain, general_category, software_category, general, backend])
    db.commit()
    return general, backend


def test_unknown_ai_leaf_falls_back_to_registry_default_path():
    db = _build_sqlite_session()
    try:
        general, backend = _seed_taxonomy(db)
        normalizer = JobCategoryNormalizer(db)

        resolved = normalizer.resolve_taxonomy_decision(
            {
                "source_path_decision": {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "Backend Development",
                    "resolution": "match_existing",
                },
                "final_taxonomy_decision": {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "Platform Reliability",
                    "resolution": "create_new",
                },
            },
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Developers/Programmers",
        )

        assert resolved == backend.id
        assert db.query(JobSubcategory).filter_by(name="Platform Reliability").count() == 0
    finally:
        db.close()


def test_get_category_hierarchy_can_render_compatibility_string():
    db = _build_sqlite_session()
    try:
        _, backend = _seed_taxonomy(db)
        normalizer = JobCategoryNormalizer(db)

        hierarchy = normalizer.get_category_hierarchy(backend.id)

        assert hierarchy == {
            "subcategory": "Backend Development",
            "category": "Software Development",
            "domain": "Information & Communication Technology",
        }
    finally:
        db.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/test_job_taxonomy_governance.py -q`

Expected: FAIL because the current normalizer creates a new `Platform Reliability` subcategory instead of falling back to an existing registry-backed path.

- [ ] **Step 3: Write the minimal implementation**

```python
# backend/app/services/job_category_normalizer.py
def _get_or_create_path(
    self,
    domain_name: str,
    category_name: str,
    subcategory_name: str,
    allow_create: bool = False,
) -> uuid.UUID:
    domain = self._find_domain(domain_name)
    if domain is None:
        if not allow_create:
            raise ValueError(f"Unknown governed domain: {domain_name}")
        domain = self._create_domain(domain_name)

    category = self._find_category(domain.id, category_name)
    if category is None:
        if not allow_create:
            raise ValueError(f"Unknown governed category: {category_name}")
        category = self._create_category(domain.id, category_name)

    subcategory = self._find_subcategory(category.id, subcategory_name)
    if subcategory is None:
        if not allow_create:
            raise ValueError(f"Unknown governed subcategory: {subcategory_name}")
        subcategory = self._create_subcategory(category.id, subcategory_name)

    return subcategory.id


def resolve_taxonomy_decision(...):
    ...
    source_path = self._resolve_path_from_decision(source_decision, source_slice)
    final_path = self._resolve_open_path_from_decision(
        final_decision or self._decision_from_resolved_path(source_path),
        fallback_path=source_path,
    )
    if final_path[3] and not classification.get("governance_override"):
        final_path = source_path
    domain_name, category_name, subcategory_name, allow_create = self._select_resolved_path(
        classification,
        source_path=source_path,
        final_path=final_path,
        conservative_mode=conservative_mode,
        cross_domain_min_confidence=cross_domain_min_confidence,
    )
    return self._get_or_create_path(
        domain_name,
        category_name,
        subcategory_name,
        allow_create=allow_create if classification.get("governance_override") else False,
    )
```

```python
# backend/app/services/ai_enrichment_service.py
job.ai_category = (
    self._build_compatibility_category(accepted_hierarchy)
    or classification.get("compatibility_category")
    or classification.get("category")
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_job_taxonomy_governance.py backend/tests/test_skill_governance.py -q`

Expected: PASS for the new taxonomy tests and no regression in existing enrichment tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/job_category_normalizer.py backend/app/services/ai_enrichment_service.py backend/tests/test_job_taxonomy_governance.py
git commit -m "feat: enforce canonical job taxonomy resolution"
```

## Task 2: Add Raw Skill Mention Persistence

**Files:**

- Create: `backend/app/models/job_skill_mention.py`
- Create: `backend/app/repositories/job_skill_mention_repository.py`
- Create: `backend/alembic/versions/20260501_103000_add_job_skill_mentions.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/tests/test_skill_governance.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_skill_governance.py
from app.models.job_skill_mention import JobSkillMention


@pytest.mark.asyncio
async def test_ai_enrichment_service_writes_skill_mentions_for_all_resolutions():
    ...
    await service.enrich_job(job, db)

    mentions = db.query(JobSkillMention).filter_by(job_id=job.id).order_by(JobSkillMention.raw_name.asc()).all()

    assert [(m.raw_name, m.resolution) for m in mentions] == [
        ("GraphQL", "review_candidate"),
        ("Project Management", "generic_tag"),
        ("React", "match_existing"),
    ]
    assert [m.skill_id for m in mentions if m.raw_name == "React"] == [react.id]
    assert [m.generic_tag for m in mentions if m.raw_name == "Project Management"] == ["Project Management"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/test_skill_governance.py -q`

Expected: FAIL because `JobSkillMention` does not exist and enrichment does not persist raw mention audit rows.

- [ ] **Step 3: Write the minimal implementation**

```python
# backend/app/models/job_skill_mention.py
from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class JobSkillMention(Base):
    __tablename__ = "job_skill_mentions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_name = Column(String(100), nullable=False)
    normalized_name = Column(String(100), nullable=False, index=True)
    resolution = Column(String(32), nullable=False, index=True)
    skill_id = Column(UUID(as_uuid=True), ForeignKey("skills.id", ondelete="SET NULL"), nullable=True, index=True)
    review_candidate_id = Column(UUID(as_uuid=True), ForeignKey("skill_review_candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    generic_tag = Column(String(100), nullable=True)
    source = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    job = relationship("Job")
    skill = relationship("Skill")
    review_candidate = relationship("SkillReviewCandidate")
```

```python
# backend/app/repositories/job_skill_mention_repository.py
from app.models.job_skill_mention import JobSkillMention


class JobSkillMentionRepository:
    def create_mention(
        self,
        db,
        *,
        job_id,
        raw_name,
        normalized_name,
        resolution,
        skill_id=None,
        review_candidate_id=None,
        generic_tag=None,
        source="ai",
        confidence=None,
    ):
        mention = JobSkillMention(
            job_id=job_id,
            raw_name=raw_name,
            normalized_name=normalized_name,
            resolution=resolution,
            skill_id=skill_id,
            review_candidate_id=review_candidate_id,
            generic_tag=generic_tag,
            source=source,
            confidence=confidence,
        )
        db.add(mention)
        db.flush()
        return mention
```

```python
# backend/alembic/versions/20260501_103000_add_job_skill_mentions.py
revision = "20260501_103000"
down_revision = "20260430_140000"


def upgrade() -> None:
    op.create_table(
        "job_skill_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("review_candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generic_tag", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["review_candidate_id"], ["skill_review_candidates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_skill_mentions_job_id", "job_skill_mentions", ["job_id"], unique=False)
    op.create_index("ix_job_skill_mentions_skill_id", "job_skill_mentions", ["skill_id"], unique=False)
    op.create_index("ix_job_skill_mentions_resolution", "job_skill_mentions", ["resolution"], unique=False)
    op.create_index("ix_job_skill_mentions_normalized_name", "job_skill_mentions", ["normalized_name"], unique=False)
```

- [ ] **Step 4: Run the tests and migration**

Run: `pytest backend/tests/test_skill_governance.py -q`

Expected: PASS with mention rows created for each enrichment resolution.

Run: `cd backend && DATABASE_URL=postgresql://admin:dev_password@localhost:5433/jobsdb alembic upgrade head`

Expected: Alembic upgrades cleanly and adds `job_skill_mentions`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/job_skill_mention.py backend/app/repositories/job_skill_mention_repository.py backend/app/models/__init__.py backend/alembic/versions/20260501_103000_add_job_skill_mentions.py backend/tests/test_skill_governance.py
git commit -m "feat: persist raw job skill mentions"
```

## Task 3: Route Enrichment Away From Polluted Canonical Skills

**Files:**

- Modify: `backend/app/services/skill_normalizer.py`
- Modify: `backend/app/services/ai_enrichment_service.py`
- Modify: `backend/app/repositories/job_skill_repository.py`
- Modify: `backend/tests/test_skill_governance.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_skill_normalizer_does_not_treat_other_general_auto_skill_as_canonical_match():
    db = _build_sqlite_session()
    try:
        category = SkillCategory(id=uuid.uuid4(), name="Other", created_by="ai", is_auto_created=True)
        technology = SkillTechnology(id=uuid.uuid4(), category_id=category.id, name="General", created_by="ai", is_auto_created=True)
        polluted = Skill(id=uuid.uuid4(), technology_id=technology.id, name="Linux", created_by="ai", is_auto_created=True)
        db.add_all([category, technology, polluted])
        db.commit()

        decision = SkillNormalizer(db).resolve_extracted_skill(
            {"name": "Linux", "kind": "technical", "resolution": "match_existing"}
        )

        assert decision["action"] == "review_candidate"
        assert decision["normalized_name"] == "Linux"
    finally:
        db.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/test_skill_governance.py -q`

Expected: FAIL because the current normalizer will match the polluted `Other / General` `Linux` skill as if it were a curated canonical leaf.

- [ ] **Step 3: Write the minimal implementation**

```python
# backend/app/services/skill_normalizer.py
def _is_polluted_auto_skill(self, skill: Skill) -> bool:
    technology = getattr(skill, "technology", None)
    category = getattr(technology, "category", None) if technology is not None else None
    return (
        bool(skill.is_auto_created)
        and technology is not None
        and category is not None
        and category.name == "Other"
        and technology.name == "General"
    )


def resolve_extracted_skill(self, extracted_skill: Any) -> Dict[str, Any]:
    ...
    if existing_skill is not None and self._is_polluted_auto_skill(existing_skill):
        existing_skill = None

    if existing_skill is not None:
        return {
            "action": "match_existing",
            "skill_id": existing_skill.id,
            "skill_name": existing_skill.name,
            "technology_id": existing_skill.technology_id,
            "category_id": existing_skill.technology.category_id,
        }
```

```python
# backend/app/services/ai_enrichment_service.py
mention_repo = JobSkillMentionRepository()

for extracted_skill in extracted_skills:
    decision = skill_normalizer.resolve_extracted_skill(extracted_skill)
    raw_name = str(skill_normalizer._coerce_payload(extracted_skill).get("name") or "").strip()

    if action == "generic_tag":
        mention_repo.create_mention(
            db,
            job_id=job.id,
            raw_name=raw_name,
            normalized_name=generic_tag,
            resolution="generic_tag",
            generic_tag=generic_tag,
            confidence=insight.get("confidence"),
        )
        ...
    elif action == "review_candidate":
        candidate = skill_normalizer.register_review_candidate(...)
        mention_repo.create_mention(
            db,
            job_id=job.id,
            raw_name=raw_name,
            normalized_name=str(decision.get("normalized_name") or ""),
            resolution="review_candidate",
            review_candidate_id=candidate.id,
            confidence=insight.get("confidence"),
        )
    elif action == "match_existing":
        mention_repo.create_mention(
            db,
            job_id=job.id,
            raw_name=raw_name,
            normalized_name=skill.name,
            resolution="match_existing",
            skill_id=skill_id,
            confidence=insight.get("confidence"),
        )
        job_skill_repo.create_job_skill(...)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_skill_governance.py backend/tests/test_skill_history_governance.py -q`

Expected: PASS with polluted `Other / General` skills routed to review instead of being silently reinforced as canonical matches.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/skill_normalizer.py backend/app/services/ai_enrichment_service.py backend/app/repositories/job_skill_repository.py backend/tests/test_skill_governance.py
git commit -m "feat: route enrichment through governed skill decisions"
```

## Task 4: Backfill Missing Job Taxonomy and Rebuild Job Metrics

**Files:**

- Create: `backend/scripts/govern_job_taxonomy.py`
- Modify: `backend/scripts/verify_migration.py`
- Modify: `backend/tests/test_job_taxonomy_governance.py`

- [ ] **Step 1: Write the failing tests**

```python
from scripts.govern_job_taxonomy import backfill_unmapped_jobs, rebuild_job_taxonomy_metrics


def test_backfill_unmapped_jobs_assigns_default_slice_path():
    db = _build_sqlite_session()
    try:
        general, backend = _seed_taxonomy(db)
        company = Company(id=uuid.uuid4(), company_id="company-1", name="Company 1")
        job = Job(
            id=uuid.uuid4(),
            job_id="job-1",
            source_site="jobsdb",
            company_id=company.id,
            title="Unmapped role",
            description="Needs fallback",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Unknown Source Bucket",
        )
        db.add_all([company, job])
        db.commit()

        updated = backfill_unmapped_jobs(db, execute=True)

        db.refresh(job)
        assert updated == 1
        assert job.subcategory_id == general.id
    finally:
        db.close()


def test_rebuild_job_taxonomy_metrics_recomputes_distinct_job_count():
    db = _build_sqlite_session()
    try:
        general, backend = _seed_taxonomy(db)
        company = Company(id=uuid.uuid4(), company_id="company-1", name="Company 1")
        jobs = [
            Job(id=uuid.uuid4(), job_id="job-1", source_site="jobsdb", company_id=company.id, title="A", subcategory_id=backend.id),
            Job(id=uuid.uuid4(), job_id="job-2", source_site="jobsdb", company_id=company.id, title="B", subcategory_id=backend.id),
        ]
        db.add(company)
        db.add_all(jobs)
        db.commit()

        rebuild_job_taxonomy_metrics(db)

        db.refresh(backend)
        assert backend.distinct_job_count == 2
        assert backend.category.distinct_job_count == 2
        assert backend.category.domain.distinct_job_count == 2
    finally:
        db.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/test_job_taxonomy_governance.py -q`

Expected: FAIL because `govern_job_taxonomy.py` and its backfill/metrics functions do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
# backend/scripts/govern_job_taxonomy.py
from sqlalchemy import func

from app.config import settings
from app.models import Job, JobCategory, JobDomain, JobSubcategory
from app.services.job_category_normalizer import JobCategoryNormalizer


def backfill_unmapped_jobs(db, *, execute: bool = False) -> int:
    normalizer = JobCategoryNormalizer(db)
    jobs = (
        db.query(Job)
        .filter(Job.is_deleted.is_(False), Job.subcategory_id.is_(None), Job.source_classification_id.isnot(None), Job.source_classification_id != "")
        .all()
    )
    updated = 0
    for job in jobs:
        job.subcategory_id = normalizer.resolve_taxonomy_decision(
            {},
            source_classification_id=job.source_classification_id,
            source_classification_name=job.source_classification_name,
            source_subclassification_name=job.source_subclassification_name,
        )
        updated += 1
    rebuild_job_taxonomy_metrics(db)
    if execute:
        db.commit()
    else:
        db.rollback()
    return updated


def rebuild_job_taxonomy_metrics(db) -> None:
    db.query(JobSubcategory).update({JobSubcategory.usage_count: 0, JobSubcategory.distinct_job_count: 0, JobSubcategory.is_filter_visible: False}, synchronize_session=False)
    db.query(JobCategory).update({JobCategory.usage_count: 0, JobCategory.distinct_job_count: 0, JobCategory.is_filter_visible: False}, synchronize_session=False)
    db.query(JobDomain).update({JobDomain.usage_count: 0, JobDomain.distinct_job_count: 0, JobDomain.is_filter_visible: False}, synchronize_session=False)
    db.flush()
    ...
```

```python
# backend/scripts/verify_migration.py
"jobs_without_subcategory": {
    "query": """
        SELECT COUNT(*) FROM jobs
        WHERE subcategory_id IS NULL AND is_deleted = false
    """,
    "allow_missing": True,
},
```

- [ ] **Step 4: Run the tests and dry-run scripts**

Run: `pytest backend/tests/test_job_taxonomy_governance.py backend/tests/test_skill_history_governance.py -q`

Expected: PASS with deterministic backfill and counter rebuild behavior covered.

Run: `DATABASE_URL=postgresql://admin:dev_password@localhost:5433/jobsdb python backend/scripts/govern_job_taxonomy.py audit`

Expected: Report the current unmapped-job count before execution.

Run: `DATABASE_URL=postgresql://admin:dev_password@localhost:5433/jobsdb python backend/scripts/govern_job_taxonomy.py apply --dry-run`

Expected: Show how many jobs would be mapped and rebuilt without committing changes.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/govern_job_taxonomy.py backend/scripts/verify_migration.py backend/tests/test_job_taxonomy_governance.py
git commit -m "feat: add governed job taxonomy backfill"
```

## Task 5: Extend Historical Skill Governance and Verification

**Files:**

- Modify: `backend/scripts/govern_skill_history.py`
- Modify: `backend/scripts/verify_migration.py`
- Modify: `backend/tests/test_skill_history_governance.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_apply_skill_history_governance_moves_single_job_phrase_to_review(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        other_category, other_general = _create_skill_hierarchy(db, "Other", "General")
        phrase_skill = _create_skill(
            db,
            other_general.id,
            "Technology solutions implementation lifecycle",
        )
        job = _create_job(db, company.id, "Delivery Lead")
        _link_job_skill(db, job.id, phrase_skill.id)
        db.commit()

        curations_path = _write_curations(tmp_path, {}, minimum_distinct_jobs=1)

        report = govern_skill_history.apply_skill_history_governance(
            db,
            min_distinct_jobs=1,
            curation_path=curations_path,
            execute=False,
        )

        review_names = {
            entry["source_skill"]["name"]
            for entry in report["entries"]
            if entry["action"] == "review"
        }
        assert "Technology solutions implementation lifecycle" in review_names
    finally:
        db.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/test_skill_history_governance.py -q`

Expected: FAIL because low-frequency polluted phrase handling is not explicitly covered in the current audit/apply flow.

- [ ] **Step 3: Write the minimal implementation**

```python
# backend/scripts/govern_skill_history.py
def _looks_phrase_like(name: str) -> bool:
    normalized = normalize_lookup_key(name)
    return len(normalized.split()) >= 4


def _classify_skill_row(row: dict[str, Any], curations: dict[str, Any]) -> dict[str, Any]:
    source_name = row["skill_name"]
    normalized_name = normalize_lookup_key(source_name)
    curation = dict(curations["entries"].get(normalized_name) or {})

    if not curation and row["distinct_jobs"] <= 1 and _looks_phrase_like(source_name):
        curation = {"action": "review", "note": "Phrase-like one-off skill mention"}

    action = str(curation.get("action") or "review").strip()
    ...
```

```python
# backend/scripts/verify_migration.py
"job_skill_mentions_total": {
    "query": "SELECT COUNT(*) FROM job_skill_mentions",
    "allow_missing": True,
},
"polluted_other_general_skills": {
    "query": """
        SELECT COUNT(*)
        FROM skills s
        JOIN skill_technologies st ON s.technology_id = st.id
        JOIN skill_categories sc ON st.category_id = sc.id
        WHERE lower(sc.name) = 'other'
          AND lower(st.name) = 'general'
    """,
    "allow_missing": True,
},
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_skill_history_governance.py -q`

Expected: PASS with one-off phrase-like polluted skills routed into review.

Run: `DATABASE_URL=postgresql://admin:dev_password@localhost:5433/jobsdb python backend/scripts/govern_skill_history.py audit --min-distinct-jobs 1`

Expected: Audit output includes merge/generic/review actions and reports remaining `Other / General` pollution.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/govern_skill_history.py backend/scripts/verify_migration.py backend/tests/test_skill_history_governance.py
git commit -m "feat: tighten historical skill governance"
```

## Task 6: Move Jobs and Stats APIs Toward Canonical Taxonomy

**Files:**

- Create: `backend/tests/test_api_taxonomy_compat.py`
- Modify: `backend/app/api/jobs.py`
- Modify: `backend/app/api/stats.py`
- Modify: `backend/app/schemas/job_search.py`

- [ ] **Step 1: Write the failing tests**

```python
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.api.jobs import _apply_structured_filters
from app.api.stats import get_category_stats
from app.models import Company, Job, JobCategory, JobDomain, JobSubcategory
from app.schemas.job_search import JobSearchFiltersSchema

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"


def test_legacy_category_filter_matches_canonical_subcategory_path():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Company.__table__, JobDomain.__table__, JobCategory.__table__, JobSubcategory.__table__, Job.__table__])
    Session = sessionmaker(bind=engine)
    db = Session()
    ...
    filters = JobSearchFiltersSchema(category="Information & Communication Technology / Software Development / Backend Development")
    query = _apply_structured_filters(db.query(Job).join(Company), filters)
    assert [job.job_id for job in query.all()] == ["job-1"]


@pytest.mark.asyncio
async def test_category_stats_group_by_canonical_taxonomy_path():
    ...
    results = await get_category_stats(db=db)
    assert results[0]["category"] == "Information & Communication Technology / Software Development / Backend Development"
    assert results[0]["count"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/test_api_taxonomy_compat.py -q`

Expected: FAIL because the current jobs filter and stats endpoint still use `Job.ai_category` directly.

- [ ] **Step 3: Write the minimal implementation**

```python
# backend/app/api/jobs.py
def _apply_legacy_category_filter(query, category: str):
    parts = [part.strip() for part in category.split("/") if part.strip()]
    if len(parts) == 3:
        domain_name, category_name, subcategory_name = parts
        return (
            query.join(JobSubcategory, Job.subcategory_id == JobSubcategory.id)
            .join(JobCategory, JobSubcategory.category_id == JobCategory.id)
            .join(JobDomain, JobCategory.domain_id == JobDomain.id)
            .filter(
                JobDomain.name == domain_name,
                JobCategory.name == category_name,
                JobSubcategory.name == subcategory_name,
            )
        )
    return query.filter(Job.ai_category == category)


def _apply_structured_filters(query, filters: JobSearchFiltersSchema):
    ...
    if filters.category:
        query = _apply_legacy_category_filter(query, filters.category)
```

```python
# backend/app/api/stats.py
from sqlalchemy import case
from app.models import JobCategory, JobDomain, JobSubcategory


@router.get("/categories")
async def get_category_stats(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    compatibility_path = func.concat(
        JobDomain.name,
        " / ",
        JobCategory.name,
        " / ",
        JobSubcategory.name,
    )
    results = (
        db.query(
            case(
                (Job.subcategory_id.isnot(None), compatibility_path),
                else_=Job.ai_category,
            ).label("category"),
            func.count(Job.id).label("count"),
        )
        .outerjoin(JobSubcategory, Job.subcategory_id == JobSubcategory.id)
        .outerjoin(JobCategory, JobSubcategory.category_id == JobCategory.id)
        .outerjoin(JobDomain, JobCategory.domain_id == JobDomain.id)
        .filter(Job.is_deleted == False)
        .group_by("category")
        .order_by(desc("count"))
        .all()
    )
    return [{"category": category, "count": count} for category, count in results if category]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_api_taxonomy_compat.py -q`

Expected: PASS with legacy category strings resolving through canonical taxonomy joins first.

Run: `pytest backend/tests/test_api_taxonomy_compat.py backend/tests/test_job_taxonomy_governance.py backend/tests/test_skill_governance.py -q`

Expected: PASS with no regressions across taxonomy and enrichment behavior.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/jobs.py backend/app/api/stats.py backend/app/schemas/job_search.py backend/tests/test_api_taxonomy_compat.py
git commit -m "feat: back legacy category APIs with canonical taxonomy"
```

## Task 7: Drop Redundant Covered Indexes

**Files:**

- Create: `backend/alembic/versions/20260501_130000_drop_redundant_taxonomy_indexes.py`

- [ ] **Step 1: Write the migration review checklist as the failing artifact**

```python
# backend/alembic/versions/20260501_130000_drop_redundant_taxonomy_indexes.py
revision = "20260501_130000"
down_revision = "20260501_103000"

# Drop only these covered indexes:
# - idx_companies_company_id
# - idx_job_categories_domain_id
# - idx_job_skills_job_id
# - idx_job_subcategories_category_id
# - idx_jobs_job_id
# - idx_skills_name
# - idx_skills_technology_id
```

- [ ] **Step 2: Run the verification before editing**

Run: `DATABASE_URL=postgresql://admin:dev_password@localhost:5433/jobsdb python backend/scripts/verify_migration.py`

Expected: Current verification report prints existing coverage before index cleanup.

- [ ] **Step 3: Write the migration**

```python
# backend/alembic/versions/20260501_130000_drop_redundant_taxonomy_indexes.py
from alembic import op

revision = "20260501_130000"
down_revision = "20260501_103000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ctx = op.get_context()
    indexes = [
        ("idx_companies_company_id", "companies"),
        ("idx_job_categories_domain_id", "job_categories"),
        ("idx_job_skills_job_id", "job_skills"),
        ("idx_job_subcategories_category_id", "job_subcategories"),
        ("idx_jobs_job_id", "jobs"),
        ("idx_skills_name", "skills"),
        ("idx_skills_technology_id", "skills"),
    ]
    if ctx.dialect.name == "postgresql":
        with ctx.autocommit_block():
            for index_name, table_name in indexes:
                op.drop_index(index_name, table_name=table_name, postgresql_concurrently=True)
    else:
        for index_name, table_name in indexes:
            op.drop_index(index_name, table_name=table_name)


def downgrade() -> None:
    ctx = op.get_context()
    recreate = [
        ("idx_companies_company_id", "companies", ["company_id"]),
        ("idx_job_categories_domain_id", "job_categories", ["domain_id"]),
        ("idx_job_skills_job_id", "job_skills", ["job_id"]),
        ("idx_job_subcategories_category_id", "job_subcategories", ["category_id"]),
        ("idx_jobs_job_id", "jobs", ["job_id"]),
        ("idx_skills_name", "skills", ["name"]),
        ("idx_skills_technology_id", "skills", ["technology_id"]),
    ]
    if ctx.dialect.name == "postgresql":
        with ctx.autocommit_block():
            for index_name, table_name, columns in recreate:
                op.create_index(index_name, table_name, columns, unique=False, postgresql_concurrently=True)
    else:
        for index_name, table_name, columns in recreate:
            op.create_index(index_name, table_name, columns, unique=False)
```

- [ ] **Step 4: Run the migration and verify health**

Run: `cd backend && DATABASE_URL=postgresql://admin:dev_password@localhost:5433/jobsdb alembic upgrade head`

Expected: Migration applies cleanly.

Run: `DATABASE_URL=postgresql://admin:dev_password@localhost:5433/jobsdb python backend/scripts/verify_migration.py`

Expected: Verification still passes after index cleanup.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/20260501_130000_drop_redundant_taxonomy_indexes.py
git commit -m "chore: drop redundant covered taxonomy indexes"
```

## Self-Review

### Spec Coverage

- Canonical job taxonomy only: covered by Task 1, Task 4, and Task 6
- Raw extracted skill mention layer: covered by Task 2 and Task 3
- Historical polluted skill cleanup: covered by Task 5
- Verification and counter rebuild: covered by Task 4 and Task 5
- Redundant index cleanup: covered by Task 7

### Placeholder Scan

- No `TBD`, `TODO`, or “implement later” placeholders remain.
- Every task includes exact file paths, test commands, and commit commands.

### Type Consistency

- `job_skill_mentions` is the new raw audit table name throughout.
- Canonical job hierarchy remains `job_domains -> job_categories -> job_subcategories -> jobs.subcategory_id`.
- Controlled skill hierarchy remains `skill_categories -> skill_technologies -> skills -> job_skills`.
