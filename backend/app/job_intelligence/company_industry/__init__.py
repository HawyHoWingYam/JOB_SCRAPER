"""Governed Company Industry taxonomy and assignment interfaces."""

from app.job_intelligence.company_industry.contracts import (
    CompanyIndustryEvidence,
    CompanyIndustryOutcome,
)
from app.job_intelligence.company_industry.decisions import (
    CompanyIndustryDecisionAdapter,
    CompanyIndustryDecisionError,
)
from app.job_intelligence.company_industry.publisher import (
    CompanyIndustryActivationRef,
    CompanyIndustryPublisher,
)
from app.job_intelligence.company_industry.rebuild import (
    CompanyIndustryRebuildInspector,
    CompanyIndustryRebuildReport,
    RecoveredCompanyIndustry,
)
from app.job_intelligence.company_industry.read_model import (
    CompanyIndustry,
    CompanyIndustryAssignmentView,
    CompanyIndustryCompanyStateView,
    CompanyIndustryNodeView,
    CompanyIndustryReviewItemView,
    CompanyIndustryReviewPage,
    CompanyIndustryReviewQuery,
    CompanyIndustryReadError,
    CompanyIndustryReviewRefView,
    CompanyIndustryRevisionView,
    CompanyIndustryTreeView,
    SourceIndustryMappingView,
)

__all__ = [
    "CompanyIndustry",
    "CompanyIndustryActivationRef",
    "CompanyIndustryAssignmentView",
    "CompanyIndustryCompanyStateView",
    "CompanyIndustryDecisionAdapter",
    "CompanyIndustryDecisionError",
    "CompanyIndustryEvidence",
    "CompanyIndustryNodeView",
    "CompanyIndustryOutcome",
    "CompanyIndustryPublisher",
    "CompanyIndustryRebuildInspector",
    "CompanyIndustryRebuildReport",
    "CompanyIndustryReadError",
    "CompanyIndustryReviewItemView",
    "CompanyIndustryReviewPage",
    "CompanyIndustryReviewQuery",
    "CompanyIndustryReviewRefView",
    "CompanyIndustryRevisionView",
    "CompanyIndustryTreeView",
    "RecoveredCompanyIndustry",
    "SourceIndustryMappingView",
]
