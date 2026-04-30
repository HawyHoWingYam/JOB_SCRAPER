"""Deprecated helper kept only to explain the old migration path."""


def migrate_skills() -> int:
    """Report that the legacy jobs.skills migration path no longer exists."""
    print(
        "The jobs.skills column has been removed. "
        "Use backend/scripts/backup_legacy_ai_data.py for archival exports or "
        "backend/scripts/batch_enrich_jobs.py to repopulate relational job_skills."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(migrate_skills())
