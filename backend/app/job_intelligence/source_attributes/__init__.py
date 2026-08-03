"""Source-owned Job classification and employment evidence."""

from app.job_intelligence.source_attributes.adapters import (
    CTGoodJobsSourceEvidenceAdapter,
    JobsDBSourceEvidenceAdapter,
    OfferTodaySourceEvidenceAdapter,
)
from app.job_intelligence.source_attributes.contracts import (
    EmploymentTypeView,
    ProjectionResult,
    SourceClassificationContext,
    SourceClassificationNodeEvidence,
    SourceClassificationPathEvidence,
    SourceEmploymentLabelEvidence,
    SourceEmploymentLabelView,
    SourceJobAttributeEvidence,
    SourceJobAttributesView,
)
from app.job_intelligence.source_attributes.module import (
    EMPLOYMENT_TYPE_SEEDS,
    EmploymentTypeRegistryError,
    EmploymentTypeRegistrySyncResult,
    SourceJobAttributes,
    reconcile_employment_type_registry,
)
from app.job_intelligence.source_attributes.rebuild import (
    RecoveredSourceJobAttribute,
    SourceJobAttributeRebuildInspector,
    SourceJobAttributeRebuildReport,
    SourceRebuildInspection,
)

__all__ = [
    "CTGoodJobsSourceEvidenceAdapter",
    "EMPLOYMENT_TYPE_SEEDS",
    "EmploymentTypeRegistryError",
    "EmploymentTypeRegistrySyncResult",
    "EmploymentTypeView",
    "JobsDBSourceEvidenceAdapter",
    "OfferTodaySourceEvidenceAdapter",
    "ProjectionResult",
    "RecoveredSourceJobAttribute",
    "SourceClassificationContext",
    "SourceClassificationNodeEvidence",
    "SourceClassificationPathEvidence",
    "SourceEmploymentLabelEvidence",
    "SourceEmploymentLabelView",
    "SourceJobAttributeEvidence",
    "SourceJobAttributeRebuildInspector",
    "SourceJobAttributeRebuildReport",
    "SourceJobAttributes",
    "SourceJobAttributesView",
    "SourceRebuildInspection",
    "reconcile_employment_type_registry",
]
