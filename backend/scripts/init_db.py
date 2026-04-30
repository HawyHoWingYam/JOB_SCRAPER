#!/usr/bin/env python3
"""Initialize database tables for hierarchical taxonomy."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine, Base
import app.models  # noqa: F401  # Ensure all ORM models are registered on Base.metadata.


def init_db():
    """Create all tables."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✓ Database tables created successfully")


if __name__ == "__main__":
    init_db()
