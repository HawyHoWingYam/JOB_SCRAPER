from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re


@dataclass(frozen=True)
class IncidentObservation:
    event_id: str
    source_site: str
    phase: str
    issue_class: str
    issue_code: str | None
    issue_stage: str | None
    symptom: str
    actionable: bool


@dataclass(frozen=True)
class IncidentCluster:
    cluster_id: str
    source_site: str
    phase: str
    issue_class: str
    issue_code: str | None
    issue_stage: str | None
    normalized_symptom: str
    event_ids: tuple[str, ...]
    event_count: int
    actionable_reference: bool


_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_AUTHORIZATION = re.compile(r"(?i)authorization\s*:\s*(?:bearer\s+)?\S+")
_SECRET = re.compile(r"(?i)(?:bearer|token|api[_ -]?key)\s*[:=]?\s*\S+")
_NUMBER = re.compile(r"\b\d+\b")


def normalize_incident_symptom(value: str) -> str:
    text = _URL.sub("[url]", value)
    text = _AUTHORIZATION.sub("[credential]", text)
    text = _SECRET.sub("[credential]", text)
    text = _NUMBER.sub("[number]", text)
    return " ".join(text.casefold().split())[:500]


def cluster_incidents(
    events: tuple[IncidentObservation, ...]
) -> tuple[IncidentCluster, ...]:
    grouped: dict[tuple[str, ...], list[IncidentObservation]] = {}
    for event in events:
        normalized = normalize_incident_symptom(event.symptom)
        key = (
            event.source_site,
            event.phase,
            event.issue_class,
            event.issue_code or "",
            event.issue_stage or "",
            normalized,
        )
        grouped.setdefault(key, []).append(event)
    result = []
    for key, members in grouped.items():
        event_ids = tuple(sorted(item.event_id for item in members))
        cluster_id = hashlib.sha256("\0".join(key).encode()).hexdigest()
        result.append(
            IncidentCluster(
                cluster_id=cluster_id,
                source_site=key[0],
                phase=key[1],
                issue_class=key[2],
                issue_code=key[3] or None,
                issue_stage=key[4] or None,
                normalized_symptom=key[5],
                event_ids=event_ids,
                event_count=len(event_ids),
                actionable_reference=any(item.actionable for item in members),
            )
        )
    return tuple(sorted(result, key=lambda item: item.cluster_id))


def score_incident_triage(
    *, total_events: int, cluster_labels: tuple[tuple[bool, str | None], ...]
) -> dict[str, float | str]:
    actionable = sum(reference for reference, _ in cluster_labels)
    found = sum(
        reference
        and label in {"investigate_now", "likely_source_content_or_parser_regression"}
        for reference, label in cluster_labels
    )
    false_safe = sum(
        reference and label == "known_manual_recovery"
        for reference, label in cluster_labels
    )
    answered = sum(label is not None for _, label in cluster_labels)
    clusters = len(cluster_labels)
    recall = found / actionable if actionable else 0.0
    false_safe_rate = false_safe / actionable if actionable else 0.0
    coverage = answered / clusters if clusters else 0.0
    compression = total_events / clusters if clusters else 0.0
    passed = (
        recall >= 0.95
        and false_safe_rate <= 0.02
        and coverage >= 0.70
        and compression >= 2
    )
    return {
        "compression_ratio": compression,
        "actionable_recall": recall,
        "false_safe_rate": false_safe_rate,
        "coverage": coverage,
        "decision": "proceed_limited_review" if passed else "defer",
    }


__all__ = [
    "IncidentCluster",
    "IncidentObservation",
    "cluster_incidents",
    "normalize_incident_symptom",
    "score_incident_triage",
]
