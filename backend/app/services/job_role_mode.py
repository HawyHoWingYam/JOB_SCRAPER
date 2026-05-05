"""Resolve the skill-extraction mode for a job posting."""

from __future__ import annotations

ROLE_MODE_TECHNICAL_HEAVY = "technical_heavy"
ROLE_MODE_PRODUCT_BA_SUPPORT = "product_ba_support"

_PRODUCT_BA_SUPPORT_KEYWORDS = (
    "product manager",
    "product owner",
    "product management",
    "business analyst",
    "business analysis",
    "project manager",
    "program manager",
    "delivery manager",
    "scrum master",
    "service desk",
    "help desk",
    "application support",
    "customer support",
    "technical support",
    "support",
    "operations",
    "pmo",
)


def resolve_job_role_mode(
    *,
    title: str = "",
    source_subclassification_name: str = "",
    source_classification_name: str = "",
) -> str:
    haystack = " ".join(
        [
            str(title or ""),
            str(source_subclassification_name or ""),
            str(source_classification_name or ""),
        ]
    ).lower()
    if any(keyword in haystack for keyword in _PRODUCT_BA_SUPPORT_KEYWORDS):
        return ROLE_MODE_PRODUCT_BA_SUPPORT
    return ROLE_MODE_TECHNICAL_HEAVY


def build_role_mode_guidance(role_mode: str) -> str:
    if role_mode == ROLE_MODE_PRODUCT_BA_SUPPORT:
        return (
            "For product / BA / support roles, include concrete tools, delivery practices, "
            "analysis artifacts, and support workflows when they are explicitly named or strongly "
            "evidenced. Examples include Jira, Confluence, Product Management, Business Analysis, "
            "Requirements Gathering, User Acceptance Testing, Agile, Roadmapping, KPI Tracking, "
            "Help Desk Support, and Application Support."
        )
    return (
        "Focus on hard technical skills such as languages, frameworks, platforms, tools, "
        "infrastructure technologies, and concrete software systems."
    )
