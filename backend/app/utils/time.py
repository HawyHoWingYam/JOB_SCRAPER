from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Normalize database timestamps to timezone-aware UTC.

    SQLite commonly returns a naive value even for ``timezone=True`` columns;
    those values were originally persisted as UTC by this application.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
