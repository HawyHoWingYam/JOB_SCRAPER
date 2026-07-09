from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

JD_NOISE_TERMS = {
    "all applications will be treated in strict confidence",
    "personal data collected will be used for recruitment purposes only",
    "equal opportunity employer",
    "apply now",
}

TAG_NOISE_TERMS = {
    "hong kong",
    "kowloon",
    "new territories",
    "medical insurance",
    "annual leave",
    "double pay",
}


def clean_description_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = " ".join(raw_line.split()).strip(" -")
        if not line:
            continue
        lowered = line.lower()
        if any(term in lowered for term in JD_NOISE_TERMS):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _coerce_term(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("name", "label", "text", "value"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return " ".join(candidate.split()).strip()
        return ""
    return " ".join(str(value or "").split()).strip()


def normalize_tag_terms(
    values: Sequence[Any] | None,
    *,
    blocked_terms: Collection[str] | None = None,
    max_length: int = 15,
) -> list[str]:
    blocked = {term.lower().strip() for term in TAG_NOISE_TERMS}
    if blocked_terms is not None:
        blocked.update(
            str(term or "").lower().strip() for term in blocked_terms if str(term or "").strip()
        )

    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        candidate = _coerce_term(value)
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in blocked:
            continue
        if len(candidate) > max_length:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(candidate)
    return result
