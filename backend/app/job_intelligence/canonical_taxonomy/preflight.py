from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.job_intelligence.canonical_taxonomy.evaluator import (
    CanonicalClassifierContext,
    CanonicalEvaluationError,
    CanonicalJobTaxonomy,
)
from app.job_intelligence.source_attributes import SourceJobAttributes
from app.models.job import Job


@dataclass(frozen=True)
class CanonicalTaxonomyPreflightResult:
    """Read-only eligibility result for the canonical classifier boundary."""

    status: Literal["supported", "excluded"]
    reasons: tuple[str, ...]
    context: CanonicalClassifierContext | None = None

    @property
    def reason(self) -> str | None:
        """Return a stable persisted representation of all blocking reasons."""
        return ",".join(self.reasons) if self.reasons else None


class CanonicalTaxonomyPreflight:
    """Fail closed before a Job can cross the LLM classifier boundary."""

    def __init__(
        self,
        db: Session,
        *,
        source_attributes: SourceJobAttributes | None = None,
        canonical_taxonomy: CanonicalJobTaxonomy | None = None,
    ) -> None:
        self.source_attributes = source_attributes or SourceJobAttributes(db)
        self.canonical_taxonomy = canonical_taxonomy or CanonicalJobTaxonomy(db)

    def inspect(self, job: Job) -> CanonicalTaxonomyPreflightResult:
        try:
            evidence = self.source_attributes.get(job.id)
        except ValueError:
            return CanonicalTaxonomyPreflightResult(
                status="excluded",
                reasons=("source_classification_paths_missing",),
            )

        try:
            context = self.canonical_taxonomy.build_classifier_context(evidence)
        except CanonicalEvaluationError as exc:
            return CanonicalTaxonomyPreflightResult(
                status="excluded",
                reasons=(exc.code,),
            )

        reasons = context.blocking_reasons
        if not reasons and not context.canonical_targets:
            reasons = ("canonical_target_invalid",)
        if reasons:
            return CanonicalTaxonomyPreflightResult(
                status="excluded",
                reasons=reasons,
                context=context,
            )
        return CanonicalTaxonomyPreflightResult(
            status="supported",
            reasons=(),
            context=context,
        )
