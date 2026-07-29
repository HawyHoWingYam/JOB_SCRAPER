from sqlalchemy import and_, func, literal, or_, select

from app.api.job_search_parser import ParsedSearchClause
from app.models import Job, Company
from app.models.current_taxonomy import (
    CurrentJobSkillAssignment,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)

_NORMALIZED_SPACE_CHARS = (
    "\n",
    "\r",
    "\t",
    ".",
    ",",
    ";",
    ":",
    "/",
    "\\",
    "-",
    "_",
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    "!",
    "?",
    "&",
    "+",
    "=",
    '"',
    "'",
    "<",
    ">",
)


def normalize_search_text(value: str) -> str:
    normalized = value.lower()
    for char in _NORMALIZED_SPACE_CHARS:
        normalized = normalized.replace(char, " ")
    while "  " in normalized:
        normalized = normalized.replace("  ", " ")
    return normalized.strip()


def exact_anchor_fragments(value: str) -> tuple[str, ...]:
    """Return raw substrings that every normalized exact match must contain."""
    return tuple(normalize_search_text(value).split())


def _escape_like_fragment(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalized_column(column):
    expression = func.lower(func.coalesce(column, ""))
    for char in _NORMALIZED_SPACE_CHARS:
        expression = func.replace(expression, char, " ")
    for _ in range(8):
        expression = func.replace(expression, "  ", " ")
    return literal(" ").concat(expression).concat(literal(" "))


def _build_exact_column_clause(column, value: str):
    normalized_value = normalize_search_text(value)
    exact_condition = _normalized_column(column).like(f"% {normalized_value} %")
    anchors = [
        column.ilike(f"%{_escape_like_fragment(fragment)}%", escape="\\")
        for fragment in exact_anchor_fragments(value)
    ]
    return and_(*anchors, exact_condition) if anchors else exact_condition


def _build_skill_name_exists_clause(clause: ParsedSearchClause):
    skill_label = CurrentTaxonomyNodeRecord.labels["en"].as_string()
    if clause.clause_type == "broad":
        pattern = f"%{clause.value}%"
        condition = or_(
            skill_label.ilike(pattern),
            CurrentTaxonomyAliasRecord.alias.ilike(pattern),
        )
    else:
        condition = or_(
            _build_exact_column_clause(skill_label, clause.value),
            _build_exact_column_clause(
                CurrentTaxonomyAliasRecord.alias,
                clause.value,
            ),
        )

    return (
        select(CurrentJobSkillAssignment.job_id)
        .join(
            CurrentTaxonomyNodeRecord,
            and_(
                CurrentTaxonomyNodeRecord.taxonomy == "skill",
                CurrentTaxonomyNodeRecord.code
                == CurrentJobSkillAssignment.skill_code,
            ),
        )
        .outerjoin(
            CurrentTaxonomyAliasRecord,
            and_(
                CurrentTaxonomyAliasRecord.taxonomy == "skill",
                CurrentTaxonomyAliasRecord.node_code
                == CurrentTaxonomyNodeRecord.code,
            ),
        )
        .where(
            CurrentJobSkillAssignment.job_id == Job.id,
            CurrentTaxonomyNodeRecord.is_active.is_(True),
            CurrentTaxonomyNodeRecord.is_assignable.is_(True),
            condition,
        )
        .exists()
    )


def build_search_clause(clause: ParsedSearchClause):
    if clause.clause_type == "broad":
        pattern = f"%{clause.value}%"
        return or_(
            Job.title.ilike(pattern),
            Job.description.ilike(pattern),
            Job.ai_summary.ilike(pattern),
            Job.source_classification_name.ilike(pattern),
            Job.source_subclassification_name.ilike(pattern),
            Company.name.ilike(pattern),
            Company.ai_description.ilike(pattern),
            _build_skill_name_exists_clause(clause),
        )

    return or_(
        _build_exact_column_clause(Job.title, clause.value),
        _build_exact_column_clause(Job.description, clause.value),
        _build_exact_column_clause(Job.ai_summary, clause.value),
        _build_exact_column_clause(Job.source_classification_name, clause.value),
        _build_exact_column_clause(
            Job.source_subclassification_name,
            clause.value,
        ),
        _build_exact_column_clause(Company.name, clause.value),
        _build_exact_column_clause(Company.ai_description, clause.value),
        _build_skill_name_exists_clause(clause),
    )


def apply_parsed_clauses(query, clauses: list[ParsedSearchClause]):
    for clause in clauses:
        query = query.filter(build_search_clause(clause))
    return query
