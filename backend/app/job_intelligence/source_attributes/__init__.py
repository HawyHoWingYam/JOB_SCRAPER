"""Source-owned Job classification and employment evidence."""

from app.job_intelligence.source_attributes.adapters import (
    CTGoodJobsSourceEvidenceAdapter,
    JobsDBSourceEvidenceAdapter,
    OfferTodaySourceEvidenceAdapter,
)
from app.job_intelligence.source_attributes.contracts import (
    EmploymentTypeView,
    ProjectionResult,
    SourceCatalogRevisionRef,
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
    SourceJobAttributes,
)
from app.job_intelligence.source_attributes.rebuild import (
    SourceJobAttributeRebuildInspector,
    SourceJobAttributeRebuildReport,
    SourceRebuildInspection,
)

__all__ = [
    "CTGoodJobsSourceEvidenceAdapter",
    "EMPLOYMENT_TYPE_SEEDS",
    "EmploymentTypeView",
    "JobsDBSourceEvidenceAdapter",
    "OfferTodaySourceEvidenceAdapter",
    "ProjectionResult",
    "SourceCatalogRevisionRef",
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
]
