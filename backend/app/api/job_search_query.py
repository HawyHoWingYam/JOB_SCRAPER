from sqlalchemy import and_, func, literal, or_, select

from app.api.job_search_parser import ParsedSearchClause
from app.models import Job, Company
from app.models.skill_governance import (
    GovernedJobSkill,
    GovernedSkill,
    GovernedSkillAlias,
    SkillTaxonomyActiveRevision,
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


def _normalized_column(column):
    expression = func.lower(func.coalesce(column, ""))
    for char in _NORMALIZED_SPACE_CHARS:
        expression = func.replace(expression, char, " ")
    for _ in range(8):
        expression = func.replace(expression, "  ", " ")
    return literal(" ").concat(expression).concat(literal(" "))


def _build_skill_name_exists_clause(clause: ParsedSearchClause):
    if clause.clause_type == "broad":
        pattern = f"%{clause.value}%"
        condition = or_(
            GovernedSkill.name.ilike(pattern),
            GovernedSkillAlias.raw_alias.ilike(pattern),
        )
    else:
        normalized_value = normalize_search_text(clause.value)
        pattern = f"% {normalized_value} %"
        condition = or_(
            _normalized_column(GovernedSkill.name).like(pattern),
            _normalized_column(GovernedSkillAlias.raw_alias).like(pattern),
        )

    return (
        select(GovernedJobSkill.job_id)
        .join(
            SkillTaxonomyActiveRevision,
            and_(
                SkillTaxonomyActiveRevision.singleton_key == "skill-taxonomy",
                SkillTaxonomyActiveRevision.revision_id
                == GovernedJobSkill.taxonomy_revision_id,
            ),
        )
        .join(
            GovernedSkill,
            and_(
                GovernedJobSkill.skill_id == GovernedSkill.id,
                GovernedJobSkill.taxonomy_revision_id == GovernedSkill.revision_id,
                GovernedSkill.is_active.is_(True),
            ),
        )
        .join(
            GovernedSkillAlias,
            and_(
                GovernedSkillAlias.skill_id == GovernedSkill.id,
                GovernedSkillAlias.taxonomy_revision_id == GovernedSkill.revision_id,
            ),
        )
        .where(
            GovernedJobSkill.job_id == Job.id,
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

    normalized_value = normalize_search_text(clause.value)
    pattern = f"% {normalized_value} %"
    return or_(
        _normalized_column(Job.title).like(pattern),
        _normalized_column(Job.description).like(pattern),
        _normalized_column(Job.ai_summary).like(pattern),
        _normalized_column(Job.source_classification_name).like(pattern),
        _normalized_column(Job.source_subclassification_name).like(pattern),
        _normalized_column(Company.name).like(pattern),
        _normalized_column(Company.ai_description).like(pattern),
        _build_skill_name_exists_clause(clause),
    )


def apply_parsed_clauses(query, clauses: list[ParsedSearchClause]):
    for clause in clauses:
        query = query.filter(build_search_clause(clause))
    return query
