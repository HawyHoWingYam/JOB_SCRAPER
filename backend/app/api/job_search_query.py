from sqlalchemy import and_, func, literal

from app.api.job_search_parser import ParsedSearchClause
from app.models import Job

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


def build_search_clause(clause: ParsedSearchClause):
    """Build a Job Browser text predicate over Job Description only."""
    if clause.clause_type == "broad":
        pattern = f"%{clause.value}%"
        return Job.description.ilike(pattern)

    return _build_exact_column_clause(Job.description, clause.value)


def apply_parsed_clauses(query, clauses: list[ParsedSearchClause]):
    for clause in clauses:
        query = query.filter(build_search_clause(clause))
    return query
