from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.job_intelligence.foundation import (
    RevisionManifest,
    RevisionRef,
    RevisionStore,
    SeedValidator,
    ValidationReport,
    normalized_content_hash,
)
from app.job_intelligence.skill_governance.normalization import (
    normalize_exact_skill_key,
)
from app.job_intelligence.skill_governance.seed import (
    SKILL_SEED_RULES,
    skill_seed_content_hash,
)
from app.models.skill_governance import (
    GovernedSkill,
    GovernedSkillAlias,
    GovernedSkillCategory,
    GovernedSkillTechnology,
    SkillTaxonomyActiveRevision,
    SkillTaxonomyRelease,
)
from app.utils.time import utc_now


class SkillTaxonomyValidationError(ValueError):
    def __init__(self, report: ValidationReport) -> None:
        super().__init__("Skill taxonomy seed validation failed")
        self.report = report


class SkillTaxonomyActivationConflict(RuntimeError):
    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(
            "Skill taxonomy active revision changed: "
            f"expected version {expected}, found {actual}"
        )
        self.expected = expected
        self.actual = actual


class SkillTaxonomyPublisher:
    """Validate and publish immutable governed Skill taxonomy revisions."""

    domain = "skill-taxonomy"

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    @staticmethod
    def validate(bundle: Mapping[str, Any]) -> ValidationReport:
        return SeedValidator.validate(bundle, SKILL_SEED_RULES)

    def materialize(self, bundle: Mapping[str, Any]) -> RevisionRef:
        """Materialize one complete inactive Skill release; exact retry replays."""

        if self.db is None:
            raise RuntimeError("Skill taxonomy materialization requires a Session")
        report = self.validate(bundle)
        if not report.valid:
            raise SkillTaxonomyValidationError(report)

        taxonomy = bundle["taxonomy"]
        rules = bundle["rules"]
        backfill = bundle["backfill"]
        expected_counts = taxonomy["expected_counts"]
        aliases = self._alias_rows(bundle)
        component_hashes = {
            "taxonomy": normalized_content_hash(taxonomy),
            "rules": normalized_content_hash(rules),
            "backfill": normalized_content_hash(backfill),
        }
        manifest = RevisionManifest(
            domain=self.domain,
            release_key=str(taxonomy["release_key"]),
            content_hash=skill_seed_content_hash(bundle),
            source_metadata={
                "schema_version": taxonomy["schema_version"],
                "expected_counts": dict(expected_counts),
                "expected_alias_count": len(aliases),
                "component_hashes": component_hashes,
                "source": dict(taxonomy.get("source") or {}),
            },
        )
        revision = RevisionStore(self.db).publish(manifest)
        release = self.db.get(SkillTaxonomyRelease, revision.revision_id)
        if release is not None and release.status == "ready":
            self._require_release_identity(
                release,
                revision,
                expected_counts=expected_counts,
                expected_alias_count=len(aliases),
                component_hashes=component_hashes,
                rules=rules,
                backfill=backfill,
            )
            return revision

        if release is None:
            release = SkillTaxonomyRelease(
                revision_id=revision.revision_id,
                content_hash=revision.content_hash,
                taxonomy_hash=component_hashes["taxonomy"],
                rules_hash=component_hashes["rules"],
                backfill_hash=component_hashes["backfill"],
                rules_document=dict(rules),
                backfill_document=dict(backfill),
                expected_category_count=expected_counts["categories"],
                expected_technology_count=expected_counts["technologies"],
                expected_skill_count=expected_counts["skills"],
                expected_alias_count=len(aliases),
                status="materializing",
            )
            self.db.add(release)
            self.db.flush()
        else:
            self._require_release_identity(
                release,
                revision,
                expected_counts=expected_counts,
                expected_alias_count=len(aliases),
                component_hashes=component_hashes,
                rules=rules,
                backfill=backfill,
            )

        try:
            self._materialize_nodes(bundle, revision, aliases)
            self.db.flush()
            actual_counts = self._release_counts(revision.revision_id)
            required_counts = (
                expected_counts["categories"],
                expected_counts["technologies"],
                expected_counts["skills"],
                len(aliases),
            )
            if actual_counts != required_counts:
                raise RuntimeError(
                    "Skill taxonomy materialization count mismatch: "
                    f"expected {required_counts}, found {actual_counts}"
                )
            (
                release.materialized_category_count,
                release.materialized_technology_count,
                release.materialized_skill_count,
                release.materialized_alias_count,
            ) = actual_counts
            release.status = "ready"
            release.ready_at = utc_now()
            self.db.commit()
            return revision
        except Exception:
            self.db.rollback()
            raise

    def activate(
        self,
        revision: RevisionRef,
        *,
        expected_lock_version: int,
    ) -> SkillTaxonomyActiveRevision:
        if self.db is None:
            raise RuntimeError("Skill taxonomy activation requires a Session")
        if revision.domain != self.domain:
            raise ValueError("Skill taxonomy activation received another domain")
        if expected_lock_version < 0:
            raise ValueError("Skill taxonomy expected lock version cannot be negative")

        self._lock_activation()
        release = self.db.get(SkillTaxonomyRelease, revision.revision_id)
        if (
            release is None
            or release.status != "ready"
            or release.content_hash != revision.content_hash
        ):
            self.db.rollback()
            raise RuntimeError("Skill taxonomy activation requires a ready release")

        active = (
            self.db.query(SkillTaxonomyActiveRevision)
            .filter(SkillTaxonomyActiveRevision.singleton_key == self.domain)
            .with_for_update()
            .one_or_none()
        )
        if (
            active is not None
            and active.revision_id == revision.revision_id
            and active.content_hash == revision.content_hash
        ):
            self.db.commit()
            return active

        actual_version = active.lock_version if active is not None else 0
        if expected_lock_version != actual_version:
            self.db.rollback()
            raise SkillTaxonomyActivationConflict(
                expected=expected_lock_version,
                actual=actual_version,
            )
        if active is None:
            active = SkillTaxonomyActiveRevision(
                singleton_key=self.domain,
                revision_id=revision.revision_id,
                content_hash=revision.content_hash,
                lock_version=1,
                activated_at=utc_now(),
            )
            self.db.add(active)
        else:
            active.revision_id = revision.revision_id
            active.content_hash = revision.content_hash
            active.lock_version += 1
            active.activated_at = utc_now()
        try:
            self.db.commit()
            self.db.refresh(active)
            return active
        except Exception:
            self.db.rollback()
            raise

    def _lock_activation(self) -> None:
        assert self.db is not None
        if self.db.get_bind().dialect.name == "postgresql":
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": f"{self.domain}:activation"},
            )

    @staticmethod
    def _alias_rows(
        bundle: Mapping[str, Any],
    ) -> tuple[tuple[str, str, str, str, int], ...]:
        taxonomy = bundle["taxonomy"]
        target_by_name: dict[str, str] = {}
        collected: list[tuple[int, str, str, str, str]] = []
        for category in taxonomy["categories"]:
            for technology in category["technologies"]:
                for skill in technology["skills"]:
                    skill_code = str(skill["code"])
                    skill_name = str(skill["name"])
                    target_by_name[skill_name] = skill_code
                    collected.append(
                        (
                            0,
                            skill_code,
                            skill_name,
                            normalize_exact_skill_key(skill_name),
                            "canonical_name",
                        )
                    )
                    for alias in skill.get("aliases") or []:
                        collected.append(
                            (
                                1,
                                skill_code,
                                str(alias),
                                normalize_exact_skill_key(alias),
                                "taxonomy_alias",
                            )
                        )
        for alias, target_name in (
            bundle["rules"].get("canonical_aliases") or {}
        ).items():
            skill_code = target_by_name[str(target_name)]
            collected.append(
                (
                    2,
                    skill_code,
                    str(alias),
                    normalize_exact_skill_key(alias),
                    "curation_alias",
                )
            )

        kept: dict[str, tuple[int, str, str, str, str]] = {}
        for row in sorted(
            collected,
            key=lambda item: (item[1], item[0], item[3], item[2].casefold()),
        ):
            kept.setdefault(row[3], row)

        order_by_skill: dict[str, int] = {}
        result = []
        for _, skill_code, raw_alias, normalized_key, source in sorted(
            kept.values(),
            key=lambda item: (item[1], item[0], item[3], item[2].casefold()),
        ):
            order_by_skill[skill_code] = order_by_skill.get(skill_code, 0) + 1
            result.append(
                (
                    skill_code,
                    raw_alias,
                    normalized_key,
                    source,
                    order_by_skill[skill_code],
                )
            )
        return tuple(result)

    def _materialize_nodes(
        self,
        bundle: Mapping[str, Any],
        revision: RevisionRef,
        aliases: tuple[tuple[str, str, str, str, int], ...],
    ) -> None:
        assert self.db is not None
        skills_by_code: dict[str, GovernedSkill] = {}
        for category_index, category_seed in enumerate(
            bundle["taxonomy"]["categories"]
        ):
            category = self._category_if_missing(
                revision.revision_id,
                code=str(category_seed["code"]),
                name=str(category_seed["name"]),
                source_order=category_index + 1,
                is_active=bool(category_seed.get("is_active", True)),
                retired_at=self._retired_at(category_seed),
            )
            for technology_index, technology_seed in enumerate(
                category_seed["technologies"]
            ):
                technology = self._technology_if_missing(
                    revision.revision_id,
                    category_id=category.id,
                    code=str(technology_seed["code"]),
                    name=str(technology_seed["name"]),
                    source_order=technology_index + 1,
                    is_active=bool(technology_seed.get("is_active", True)),
                    retired_at=self._retired_at(technology_seed),
                )
                for skill_index, skill_seed in enumerate(technology_seed["skills"]):
                    skill = self._skill_if_missing(
                        revision.revision_id,
                        technology_id=technology.id,
                        code=str(skill_seed["code"]),
                        name=str(skill_seed["name"]),
                        source_order=skill_index + 1,
                        is_active=bool(skill_seed.get("is_active", True)),
                        retired_at=self._retired_at(skill_seed),
                    )
                    skills_by_code[skill.code] = skill

        for skill_code, raw_alias, normalized_key, source, source_order in aliases:
            existing = self.db.scalar(
                select(GovernedSkillAlias).where(
                    GovernedSkillAlias.taxonomy_revision_id == revision.revision_id,
                    GovernedSkillAlias.normalized_key == normalized_key,
                )
            )
            if existing is None:
                self.db.add(
                    GovernedSkillAlias(
                        taxonomy_revision_id=revision.revision_id,
                        skill_id=skills_by_code[skill_code].id,
                        raw_alias=raw_alias,
                        normalized_key=normalized_key,
                        source=source,
                        source_order=source_order,
                    )
                )
            elif existing.skill_id != skills_by_code[skill_code].id:
                raise RuntimeError(
                    f"Skill alias {normalized_key!r} is bound to another Skill"
                )

    def _category_if_missing(self, revision_id, **values) -> GovernedSkillCategory:
        assert self.db is not None
        row = self.db.scalar(
            select(GovernedSkillCategory).where(
                GovernedSkillCategory.revision_id == revision_id,
                GovernedSkillCategory.code == values["code"],
            )
        )
        if row is None:
            row = GovernedSkillCategory(revision_id=revision_id, **values)
            self.db.add(row)
            self.db.flush()
        return row

    @staticmethod
    def _retired_at(seed: Mapping[str, Any]) -> datetime | None:
        value = seed.get("retired_at")
        if value is None:
            return None
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    def _technology_if_missing(self, revision_id, **values) -> GovernedSkillTechnology:
        assert self.db is not None
        row = self.db.scalar(
            select(GovernedSkillTechnology).where(
                GovernedSkillTechnology.revision_id == revision_id,
                GovernedSkillTechnology.code == values["code"],
            )
        )
        if row is None:
            row = GovernedSkillTechnology(revision_id=revision_id, **values)
            self.db.add(row)
            self.db.flush()
        return row

    def _skill_if_missing(self, revision_id, **values) -> GovernedSkill:
        assert self.db is not None
        row = self.db.scalar(
            select(GovernedSkill).where(
                GovernedSkill.revision_id == revision_id,
                GovernedSkill.code == values["code"],
            )
        )
        if row is None:
            row = GovernedSkill(revision_id=revision_id, origin="seed", **values)
            self.db.add(row)
            self.db.flush()
        return row

    def _release_counts(self, revision_id) -> tuple[int, int, int, int]:
        assert self.db is not None
        return (
            int(
                self.db.scalar(
                    select(func.count())
                    .select_from(GovernedSkillCategory)
                    .where(GovernedSkillCategory.revision_id == revision_id)
                )
                or 0
            ),
            int(
                self.db.scalar(
                    select(func.count())
                    .select_from(GovernedSkillTechnology)
                    .where(GovernedSkillTechnology.revision_id == revision_id)
                )
                or 0
            ),
            int(
                self.db.scalar(
                    select(func.count())
                    .select_from(GovernedSkill)
                    .where(
                        GovernedSkill.revision_id == revision_id,
                        GovernedSkill.origin == "seed",
                    )
                )
                or 0
            ),
            int(
                self.db.scalar(
                    select(func.count())
                    .select_from(GovernedSkillAlias)
                    .where(GovernedSkillAlias.taxonomy_revision_id == revision_id)
                )
                or 0
            ),
        )

    @staticmethod
    def _require_release_identity(
        release: SkillTaxonomyRelease,
        revision: RevisionRef,
        *,
        expected_counts: Mapping[str, Any],
        expected_alias_count: int,
        component_hashes: Mapping[str, str],
        rules: Mapping[str, Any],
        backfill: Mapping[str, Any],
    ) -> None:
        actual = (
            release.content_hash,
            release.taxonomy_hash,
            release.rules_hash,
            release.backfill_hash,
            release.rules_document,
            release.backfill_document,
            release.expected_category_count,
            release.expected_technology_count,
            release.expected_skill_count,
            release.expected_alias_count,
        )
        expected = (
            revision.content_hash,
            component_hashes["taxonomy"],
            component_hashes["rules"],
            component_hashes["backfill"],
            dict(rules),
            dict(backfill),
            expected_counts["categories"],
            expected_counts["technologies"],
            expected_counts["skills"],
            expected_alias_count,
        )
        if actual != expected:
            raise RuntimeError("Skill taxonomy release identity is inconsistent")
