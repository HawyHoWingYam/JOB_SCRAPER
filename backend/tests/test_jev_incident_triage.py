from app.services.jev_incident_triage import (
    IncidentObservation,
    cluster_incidents,
    normalize_incident_symptom,
    score_incident_triage,
)


def test_normalization_redacts_secrets_ids_urls_and_numbers() -> None:
    value = normalize_incident_symptom(
        "Missing company 12345 at https://example.test/a?token=secret; "
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"
    )
    assert "secret" not in value
    assert "abcdef" not in value
    assert "12345" not in value
    assert "https://" not in value


def test_clustering_compresses_repeated_events_and_is_stable() -> None:
    events = tuple(
        IncidentObservation(
            event_id=f"event-{index}",
            source_site="ctgoodjobs",
            phase="detail",
            issue_class="infrastructure_failure",
            issue_code="InvalidIngestPayloadError",
            issue_stage="persist",
            symptom=f"Missing source company id 10{index} and company name",
            actionable=True,
        )
        for index in range(143)
    )
    forward = cluster_incidents(events)
    reverse = cluster_incidents(tuple(reversed(events)))
    assert forward == reverse
    assert len(forward) == 1
    assert forward[0].event_count == 143
    assert len(forward[0].event_ids) == 143


def test_metrics_keep_false_safe_and_unanswered_clusters_in_denominator() -> None:
    report = score_incident_triage(
        total_events=10,
        cluster_labels=(
            (True, "investigate_now"),
            (True, None),
            (False, "known_manual_recovery"),
        ),
    )
    assert report["compression_ratio"] == 10 / 3
    assert report["actionable_recall"] == 0.5
    assert report["coverage"] == 2 / 3
    assert report["decision"] == "defer"
