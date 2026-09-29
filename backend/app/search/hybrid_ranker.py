from __future__ import annotations

from datetime import UTC, datetime
import re


def _tokenize(value: str) -> set[str]:
    return {
        token for token in re.split(r"[^a-z0-9]+", str(value or "").lower()) if token
    }


def _cosine_similarity(lhs: list[float], rhs: list[float]) -> float:
    numerator = sum(left * right for left, right in zip(lhs, rhs))
    lhs_magnitude = sum(value * value for value in lhs) ** 0.5
    rhs_magnitude = sum(value * value for value in rhs) ** 0.5
    if lhs_magnitude == 0 or rhs_magnitude == 0:
        return 0.0
    return numerator / (lhs_magnitude * rhs_magnitude)


def _description_score(query_tokens: set[str], description: str | None) -> float:
    haystack_tokens = _tokenize(description or "")
    if not query_tokens or not haystack_tokens:
        return 0.0
    return len(query_tokens & haystack_tokens) / len(query_tokens)


def _freshness_score(posted_date) -> float:
    if posted_date is None:
        return 0.0
    if posted_date.tzinfo is None:
        posted_date = posted_date.replace(tzinfo=UTC)
    age_days = max(0, (datetime.now(UTC) - posted_date).days)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.7
    if age_days <= 90:
        return 0.4
    return 0.0


def rank_hybrid_rows(rows, *, query_text: str, query_vector):
    query_tokens = _tokenize(query_text)
    ranked = []
    for job, company, embedding_row in rows:
        semantic_score = _cosine_similarity(
            list(embedding_row.embedding), list(query_vector)
        )
        description_score = _description_score(
            query_tokens,
            getattr(job, "description", None),
        )
        freshness_score = _freshness_score(getattr(job, "posted_date", None))
        combined_score = (
            (semantic_score * 0.80)
            + (description_score * 0.15)
            + (freshness_score * 0.05)
        )
        ranked.append(
            (
                combined_score,
                semantic_score,
                freshness_score,
                job,
                company,
            )
        )

    ranked.sort(
        key=lambda entry: (
            entry[0],
            entry[1],
            entry[2],
            entry[3].posted_date or datetime.min.replace(tzinfo=UTC),
            entry[3].title or "",
        ),
        reverse=True,
    )
    return [(job, company) for _, _, _, job, company in ranked]
