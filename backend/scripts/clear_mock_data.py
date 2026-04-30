"""Clear mock data produced by MockClient."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import engine
from sqlalchemy import text

def clear_mock_data():
    """Remove all AI-generated data from database."""
    with engine.connect() as conn:
        # Clear AI-generated job skills
        result = conn.execute(text("DELETE FROM job_skills WHERE source = 'ai'"))
        print(f"✓ Deleted {result.rowcount} AI job-skill associations")

        # Clear all skills (will be regenerated)
        result = conn.execute(text("DELETE FROM skills"))
        print(f"✓ Deleted {result.rowcount} skills")

        # Reset AI enrichment flags
        result = conn.execute(text(
            "UPDATE jobs SET ai_enriched_at = NULL, ai_category = NULL "
            "WHERE ai_enriched_at IS NOT NULL"
        ))
        print(f"✓ Reset {result.rowcount} jobs")

        conn.commit()
        print("\n✓ All mock data cleared successfully")

if __name__ == "__main__":
    clear_mock_data()
